import base64
import json
import subprocess
from logging import Logger
from typing import Any, Final

import interlink as i
import kubernetes.client.exceptions as k_exceptions
import pydash as _
from injector import inject
from kubernetes import client as k
from kubernetes.client.api import CoreV1Api
from kubernetes.client.api_client import ApiClient
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import Error as HelmError

from app.common.config import Config, Option
from app.entities import mappers

from .base_service import BaseService

_I_SRC_UID_KEY: Final = "interlink.io/source.uid"
_I_SRC_POD_UID_KEY: Final = "interlink.io/source.pod_uid"
_I_SRC_NAME_KEY: Final = "interlink.io/source.name"
_I_SRC_NS_KEY: Final = "interlink.io/source.namespace"
_I_RMT_PVC_KEY: Final = "interlink.io/remote-pvc"  # comma-separated list of PVC names
_I_RMT_PVC_RETENTION_POLICY_KEY: Final = "interlink.io/pvc-retention-policy"  # "delete" or "retain"
_I_PRE_EXEC_KEY: Final = "slurm-job.vk.io/pre-exec"
_I_COMMON_LABELS: Final = {"interlink.io": "offloading"}

_MAX_K8S_SEGMENT_NAME: Final = 63
_MAX_HELM_RELEASE_NAME: Final = 53

_INSTALL_WITH_PYHELM_CLIENT: Final = False


class KubernetesPluginService(BaseService):

    _k_core_client: CoreV1Api  # Kubernetes Core client to manage core resources (e.g., pods, services, namespaces)
    _k_api_client: ApiClient  # Just needed to (de)serialize dict to K8s model
    _h_client: HelmClient
    _offloading_params: dict[str, Any]

    @inject
    def __init__(self, config: Config, logger: Logger, k_core_client: k.CoreV1Api, h_client: HelmClient):
        super().__init__(config, logger)
        self._k_core_client = k_core_client
        self._k_api_client = k_core_client.api_client  # type: ignore
        self._h_client = h_client

        self._offloading_params = {
            "namespace_prefix": config.get(Option.OFFLOADING_NAMESPACE_PREFIX, ""),
            "namespace_prefix_exclusions": json.loads(config.get(Option.OFFLOADING_NAMESPACE_PREFIX_EXCLUSIONS, "[]")),
            "node_selector": None,
            "node_tolerations": None,
        }
        if config.get(Option.OFFLOADING_NODE_SELECTOR):
            self._offloading_params["node_selector"] = json.loads(config.get(Option.OFFLOADING_NODE_SELECTOR))
        if config.get(Option.OFFLOADING_NODE_TOLERATIONS):
            self._offloading_params["node_tolerations"] = json.loads(config.get(Option.OFFLOADING_NODE_TOLERATIONS))

    async def get_status(self, i_pods: list[i.PodRequest]) -> list[i.PodStatus]:
        status: list[i.PodStatus] = []
        for i_pod in i_pods:
            try:
                assert i_pod.metadata.name and i_pod.metadata.namespace and i_pod.metadata.uid

                remote_pod: k.V1Pod = self._k_core_client.read_namespaced_pod_status(
                    name=self._scope_obj_name(i_pod.metadata.name, pod_uid=i_pod.metadata.uid),
                    namespace=self._scope_ns_name(i_pod.metadata.namespace),
                )

                assert remote_pod.metadata and remote_pod.status

                remote_container_statuses: list[k.V1ContainerStatus] = remote_pod.status.container_statuses or []
                i_container_statuses: list[i.ContainerStatus] = []
                for cs in remote_container_statuses:
                    i_cs = mappers.map_k_model_to_i_model(self._k_api_client, cs, i.ContainerStatus)
                    if cs.state and cs.state.running and cs.state.running.started_at:
                        assert i_cs.state.running
                        i_cs.state.running.started_at = cs.state.running.started_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    i_container_statuses.append(i_cs)

                i_pod_status = i.PodStatus(
                    uid=i_pod.metadata.uid,
                    jid=remote_pod.metadata.uid,
                    name=i_pod.metadata.name,
                    namespace=i_pod.metadata.namespace,
                    containers=i_container_statuses,
                )

                status.append(i_pod_status)

                # self.logger.debug(
                #     "Pod '%s' in '%s' status: %s",
                #     remote_pod.metadata.name,
                #     remote_pod.metadata.namespace,
                #     str(i_pod_status.containers),
                # )
            except k_exceptions.ApiException as api_exception:
                self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
        return status

    async def get_logs(self, i_log_req: i.LogRequest) -> str:
        """
        Logs are new-line separated strings, e.g.:
        '2024-09-20T09:26:33.653884634+02:00 Listening on port 8181.\n
         2024-09-20T09:31:26.751801413+02:00 {"name": "test"}\n
        """
        logs: str = self._k_core_client.read_namespaced_pod_log(
            name=self._scope_obj_name(i_log_req.pod_name, pod_uid=i_log_req.pod_uid),
            namespace=self._scope_ns_name(i_log_req.namespace),
            timestamps=i_log_req.opts.timestamps,
            previous=i_log_req.opts.previous,
            follow=False,  # i_log_req.opts.follow,
            _preload_content=True,  # not i_log_req.opts.follow
            tail_lines=i_log_req.opts.tail or None,
            limit_bytes=i_log_req.opts.limit_bytes or None,
            since_seconds=i_log_req.opts.since_seconds or None,
        )

        # TODO if follow, you'll get a generator
        # See also https://github.com/kubernetes-client/python/issues/199

        return logs

    async def create_pod(self, i_pod_with_volumes: i.Pod) -> i.CreateStruct:
        self.logger.info("Creating Pod")

        result: i.CreateStruct

        try:
            # create namespace
            assert i_pod_with_volumes.pod.metadata.namespace
            self._create_offloading_namespace(i_pod_with_volumes.pod.metadata.namespace)

            # create POD's volumes
            for i_volume in i_pod_with_volumes.container:
                assert i_pod_with_volumes.pod.metadata.uid
                if i_volume.config_maps:
                    self._create_config_maps(i_volume.config_maps, pod_uid=i_pod_with_volumes.pod.metadata.uid)
                if i_volume.secrets:
                    self._create_secrets(i_volume.secrets, pod_uid=i_pod_with_volumes.pod.metadata.uid)
                if i_volume.persistent_volume_claims:
                    self._create_pvcs(
                        i_volume.persistent_volume_claims,
                        pod_uid=i_pod_with_volumes.pod.metadata.uid,
                        pod_metadata=i_pod_with_volumes.pod.metadata,
                    )
            # create POD
            result = await self._create_pod(i_pod_with_volumes.pod)
        except Exception as exc:
            self.logger.error("Got an exception while creating Pod (trigger rollback): %s", exc)
            await self.delete_pod(i_pod_with_volumes.pod, rollback=True)
            raise exc

        return result

    async def delete_pod(self, i_pod: i.PodRequest, rollback=False) -> str:
        self.logger.info(f"Deleting Pod (rollback={rollback})")
        assert i_pod.metadata.uid and i_pod.metadata.name and i_pod.metadata.namespace

        pod_name = self._scope_obj_name(i_pod.metadata.name, pod_uid=i_pod.metadata.uid)
        pod_namespace = self._scope_ns_name(i_pod.metadata.namespace)

        if not rollback:
            self.logger.info("Delete Pod '%s' in '%s'", pod_name, pod_namespace)
        try:
            self._k_core_client.delete_namespaced_pod(name=pod_name, namespace=pod_namespace)
        except k_exceptions.ApiException as api_exception:
            if not rollback:
                self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")

        if self.config.get(Option.TCP_TUNNEL_ENABLED):
            await self._install_bastion_release(i_pod, uninstall=True, rollback=rollback)

        if i_pod.spec and i_pod.spec.volumes:
            for volume in i_pod.spec.volumes:
                if volume.config_map:
                    cm_name = self._scope_obj_name(volume.config_map.name, pod_uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete ConfigMap '%s' in '%s'", cm_name, pod_namespace)
                    try:
                        self._k_core_client.delete_namespaced_config_map(cm_name, pod_namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
                if volume.secret:
                    secret_name = self._scope_obj_name(volume.secret.secret_name, pod_uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete Secret '%s' in '%s'", secret_name, pod_namespace)
                    try:
                        self._k_core_client.delete_namespaced_secret(secret_name, pod_namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
                if volume.persistent_volume_claim:
                    pvc_name = volume.persistent_volume_claim.claim_name  # PVC name is not scoped to POD uid
                    if remote_pvc := self._find_namespaced_pvc(pvc_name, pod_namespace):
                        assert remote_pvc.metadata
                        to_be_deleted = self._check_annotation_value(
                            remote_pvc.metadata.annotations, _I_RMT_PVC_RETENTION_POLICY_KEY, "delete"
                        )
                        if to_be_deleted:
                            if not rollback:
                                self.logger.info("Delete PVC '%s' in '%s'", pvc_name, pod_namespace)
                            try:
                                self._k_core_client.delete_namespaced_persistent_volume_claim(pvc_name, pod_namespace)
                            except k_exceptions.ApiException as api_exception:
                                if not rollback:
                                    self.logger.error(
                                        f"{api_exception.status} {api_exception.reason}: {api_exception.body}"
                                    )

        return f"Pod '{i_pod.metadata.uid}' deleted"

    def _create_offloading_namespace(self, name: str):
        scoped_ns = self._scope_ns_name(name)
        # Check whether we need to create the offloading namepsace
        # Notice that we list them all, as the offloading namespace could be a preexisting one.
        namespaces: k.V1NamespaceList = self._k_core_client.list_namespace()
        # namespaces: k.V1NamespaceList = self._k_core_client.list_namespace(
        #     label_selector=",".join([f"{key}={value}" for key, value in _I_COMMON_LABELS.items()])
        # )
        assert isinstance(namespaces.items, list)
        if _.find(namespaces.items, lambda item: item.metadata.name == scoped_ns if item.metadata else False):
            self.logger.info("Namespace '%s' already exists", scoped_ns)
        else:
            self._k_core_client.create_namespace(
                k.V1Namespace(
                    api_version="v1",
                    kind="Namespace",
                    metadata=k.V1ObjectMeta(name=scoped_ns, labels=_I_COMMON_LABELS),
                )
            )
            self.logger.info("Namespace '%s' created", scoped_ns)

    async def _create_pod(self, i_pod: i.PodRequest) -> i.CreateStruct:
        assert i_pod.metadata.uid

        metadata: k.V1ObjectMeta = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.metadata, k.V1ObjectMeta)
        self._scope_metadata(metadata, metadata, pod_uid=i_pod.metadata.uid)

        pod_spec: k.V1PodSpec = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.spec, k.V1PodSpec)
        self._filter_volumes(pod_spec, metadata, pod_uid=i_pod.metadata.uid)

        if self._offloading_params["node_selector"]:
            pod_spec.node_selector = self._offloading_params["node_selector"]
        if self._offloading_params["node_tolerations"]:
            pod_spec.tolerations = [k.V1Toleration(**t) for t in self._offloading_params["node_tolerations"]]

        if metadata.annotations and _I_PRE_EXEC_KEY in metadata.annotations:
            pre_exec_cmd = metadata.annotations[_I_PRE_EXEC_KEY]
            self._add_pre_exec_init_container(pod_spec, metadata, pre_exec_cmd)
            # Debug: run pod with privileged containers
            # for container in pod_spec.containers or []:
            #     container.security_context = k.V1SecurityContext(privileged=True)

        pod = k.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=metadata,
            spec=pod_spec,
        )

        if str(self.config.get(Option.TCP_TUNNEL_ENABLED, "False")).lower() == "true":
            await self._install_bastion_release(i_pod)

        assert metadata.name and metadata.namespace
        remote_pod: k.V1Pod = self._k_core_client.create_namespaced_pod(namespace=metadata.namespace, body=pod)

        assert i_pod.metadata.uid and remote_pod.metadata and remote_pod.metadata.uid
        create_result = i.CreateStruct(pod_uid=i_pod.metadata.uid, pod_jid=remote_pod.metadata.uid)
        self.logger.info(
            "Pod '%s' in '%s' created, with result: %s",
            remote_pod.metadata.name,
            remote_pod.metadata.namespace,
            create_result,
        )
        return create_result

    async def _install_bastion_release(self, i_pod: i.PodRequest, uninstall=False, rollback=False):
        """
        Install/uninstall Bastion release for the given `PodRequest`.

        Raises:
            `HelmError`,
            `k_exceptions.ApiException`

        Note:
            if uninstall, exceptions are captured and not rethrown.
        """

        assert i_pod.metadata.name and i_pod.metadata.namespace and i_pod.metadata.uid

        if not self.config.get(Option.TCP_TUNNEL_GATEWAY_HOST):
            self.logger.warning(
                f"TCP tunnel gateway host is not set, skipping Bastion {"un" if uninstall else ""}installation"
            )
            return

        pod_name = self._scope_obj_name(i_pod.metadata.name, pod_uid=i_pod.metadata.uid)
        pod_ns = self._scope_ns_name(i_pod.metadata.namespace)
        bastion_rel_ns = self.config.get(Option.TCP_TUNNEL_BASTION_NAMESPACE)

        ports = self._get_container_ports(i_pod)

        for port in ports:
            bastion_rel_name = self._scope_bastion_rel_name(port, pod_uid=i_pod.metadata.uid)
            # region uninstall
            if uninstall:
                if not rollback:
                    self.logger.info("Uninstall release '%s' in '%s'", bastion_rel_name, bastion_rel_ns)
                try:
                    await self._h_client.uninstall_release(
                        bastion_rel_name,
                        namespace=bastion_rel_ns,
                        wait=False,
                        timeout="60s",
                    )
                except HelmError as helm_error:
                    if not rollback:
                        self.logger.error(helm_error)

                if not rollback:
                    self.logger.info("Delete Headless Service '%s' in '%s'", pod_name, pod_ns)
                try:
                    self._k_core_client.delete_namespaced_service(pod_name, pod_ns)
                except k_exceptions.ApiException as api_exception:
                    if not rollback:
                        self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
            # endregion / uninstall
            # region install
            else:
                self.logger.info("Create Headless Service '%s' in '%s'", pod_name, pod_ns)
                service = k.V1Service(
                    metadata=k.V1ObjectMeta(name=pod_name, namespace=pod_ns),
                    spec=k.V1ServiceSpec(
                        selector={
                            **_I_COMMON_LABELS,
                            _I_SRC_POD_UID_KEY: i_pod.metadata.uid,
                        },
                        cluster_ip="None",  # headless service
                        ports=[k.V1ServicePort(port=port, target_port=port)],
                    ),
                )
                self._k_core_client.create_namespaced_service(pod_ns, service)

                bastion_chart_path = self.config.get(Option.TCP_TUNNEL_BASTION_CHART_PATH)
                bastion_chart = await self._h_client.get_chart(bastion_chart_path)
                self.logger.info("Install release '%s' in '%s'", bastion_rel_name, bastion_rel_ns)

                values = {
                    "tunnel.gateway.host": self.config.get(Option.TCP_TUNNEL_GATEWAY_HOST),
                    "tunnel.gateway.port": self.config.get(Option.TCP_TUNNEL_GATEWAY_PORT),
                    "tunnel.gateway.ssh.privateKey": self.config.get(Option.TCP_TUNNEL_GATEWAY_SSH_PRIVATE_KEY),
                    "tunnel.service.gatewayPort": port,
                    "tunnel.service.targetPort": port,
                    "tunnel.service.targetHost": f"{pod_name}.{pod_ns}.svc",
                }

                if _INSTALL_WITH_PYHELM_CLIENT:
                    # TODO: installing with pyhelm3 is not working: SSH_PRIVATE_KEY in Kubernetes Secret is 0 bytes
                    revision = await self._h_client.install_or_upgrade_release(
                        bastion_rel_name,
                        bastion_chart,
                        values,
                        namespace=bastion_rel_ns,
                        create_namespace=True,
                        atomic=False,
                        wait=False,
                        timeout="60s",
                    )
                    self.logger.debug(f"Install completed, revision: {revision.revision}, {str(revision.status)}")
                else:
                    command = f"""helm install {bastion_rel_name} {bastion_chart_path} \
                        --kubeconfig {self.config.get(Option.K8S_KUBECONFIG_PATH, "private/k8s/kubeconfig.yaml")} \
                        --namespace tcp-tunnel --create-namespace \
                        --set tunnel.gateway.host={values["tunnel.gateway.host"]} \
                        --set tunnel.gateway.port={values["tunnel.gateway.port"]} \
                        --set tunnel.gateway.ssh.privateKey={values["tunnel.gateway.ssh.privateKey"]} \
                        --set tunnel.service.gatewayPort={values["tunnel.service.gatewayPort"]} \
                        --set tunnel.service.targetHost={values["tunnel.service.targetHost"]} \
                        --set tunnel.service.targetPort={values["tunnel.service.targetPort"]}""".split()
                    self.logger.debug(f"Running command: {command}")
                    result = subprocess.run(
                        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
                    )
                    self.logger.debug(result.stdout)
            # endregion / install

    def _add_pre_exec_init_container(self, pod_spec: k.V1PodSpec, metadata: k.V1ObjectMeta, pre_exec_cmd: str) -> None:
        """
        Add an init container to extract and create mesh.sh from heredoc in pre-exec annotation.

        If pre_exec_cmd contains a heredoc pattern for mesh.sh, this function:
        1. Extracts the heredoc content
        2. Creates an init container that writes mesh.sh to a shared emptyDir volume and executes it
        3. Adds the shared volume to the pod spec

        See reference code at:
        https://github.com/interlink-hq/interlink-slurm-plugin/blob/main/pkg/slurm/prepare.go#L1067.
        """
        heredoc_marker: Final = "EOFMESH"
        heredoc_start_pattern: Final = f"cat <<'{heredoc_marker}' > $TMPDIR/mesh.sh"

        if heredoc_start_pattern not in pre_exec_cmd:
            self.logger.debug("No mesh.sh heredoc pattern found in pre-exec annotation")
            return

        mesh_script = self._extract_heredoc(pre_exec_cmd, heredoc_marker)
        if not mesh_script:
            self.logger.warning("Failed to extract mesh.sh heredoc content")
            return

        # region Base64 encode the script content to avoid escaping issues
        encoded_script = base64.b64encode(mesh_script.encode()).decode()
        if not metadata.annotations:
            metadata.annotations = {}
        metadata.annotations[_I_PRE_EXEC_KEY + "-base64"] = encoded_script

        # region Add to pod spec the emptyDir volume
        script_volume_name: Final = "interlink-scripts"
        script_mount_path: Final = "/tmp/interlink"

        if not pod_spec.volumes:
            pod_spec.volumes = []

        pod_spec.volumes.append(k.V1Volume(name=script_volume_name, empty_dir=k.V1EmptyDirVolumeSource()))
        # endregion / Add to pod spec the emptyDir volume

        # region Add to pod spec the init container to write and execute mesh.sh
        init_container = k.V1Container(
            name="mesh-setup",
            image="alpine:latest",
            restart_policy="Always",
            command=["/bin/sh", "-c"],
            args=[
                f"""
                apk add --no-cache curl bash procps gcompat libc6-compat iproute2 util-linux shadow && \
                echo '{encoded_script}' | base64 -d > {script_mount_path}/mesh.sh && \
                sed -i 's/fg 1/fg %1/g' {script_mount_path}/mesh.sh && \
                sed -i 's|unshare \\$UNSHARE_FLAGS --net --mount \\$TMPDIR/slirp.sh|\\$TMPDIR/slirp.sh|g' \\
                    {script_mount_path}/mesh.sh && \
                sed -i 's|^./slirp4netns|#./slirp4netns|' {script_mount_path}/mesh.sh && \
                chmod 0755 {script_mount_path}/mesh.sh && \
                cat > {script_mount_path}/job-fake.sh <<'EOFWRAPPER'
#!/bin/bash
# Application wrapper that runs inside mesh network namespace
echo "INFO: Running application inside mesh network"
echo "INFO: Network interfaces:"
ip addr show || true
echo "INFO: Routes:"
ip route show || true
echo "INFO: Testing connectivity..."
ping -c 2 10.7.0.1 || echo "Warning: Cannot reach WireGuard endpoint"
echo "INFO: Mesh network is ready, keeping namespace alive..."
# Keep the container running to maintain the mesh network
sleep infinity
EOFWRAPPER
                chmod 0755 {script_mount_path}/job-fake.sh && \
                export SLURM_JOB_ID=1 && \
                export SLURM_PROCID=0 && \
                export SLURM_TMPDIR=/tmp && \
                export TMPDIR=/tmp && \
                echo "INFO: Executing mesh.sh with job-fake.sh as argument..." && \
                bash {script_mount_path}/mesh.sh {script_mount_path}/job-fake.sh
                """
            ],
            volume_mounts=[k.V1VolumeMount(name=script_volume_name, mount_path=script_mount_path)],
            security_context=k.V1SecurityContext(
                privileged=True, capabilities=k.V1Capabilities(add=["SYS_ADMIN", "NET_ADMIN", "SYS_CHROOT"])
            ),
        )

        if not pod_spec.init_containers:
            pod_spec.init_containers = []
        pod_spec.init_containers.append(init_container)
        # endregion / Add to pod spec the init container to write and execute mesh.sh

    def _extract_heredoc(self, text: str, marker: str) -> str:
        """Extract heredoc content between markers."""
        start_pattern = f"<<'{marker}'"
        end_pattern = f"\n{marker}"

        start_idx = text.find(start_pattern)
        if start_idx == -1:
            return ""

        # Find the end of the line containing the start pattern
        content_start = text.find("\n", start_idx)
        if content_start == -1:
            return ""
        content_start += 1  # Move past the newline

        # Find the end marker
        end_idx = text.find(end_pattern, content_start)
        if end_idx == -1:
            return ""

        return text[content_start:end_idx]

    def _remove_heredoc(self, text: str, marker: str) -> str:
        """Remove heredoc section from text."""
        start_pattern = f"cat <<'{marker}'"
        end_pattern = f"\n{marker}"

        start_idx = text.find(start_pattern)
        if start_idx == -1:
            return text

        # Find the end marker (including the newline after it)
        end_idx = text.find(end_pattern, start_idx)
        if end_idx == -1:
            return text

        # Move past the end marker and its newline
        end_idx = text.find("\n", end_idx + len(end_pattern))
        if end_idx == -1:
            # If no newline after marker, remove to end
            return text[:start_idx].rstrip()

        # Remove the heredoc section
        return text[:start_idx] + text[end_idx + 1 :]

    def _create_config_maps(self, i_config_maps: list[i.ConfigMap], *, pod_uid: str) -> list[k.V1ConfigMap]:
        results = []

        for i_config_map in i_config_maps:
            cm_metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_config_map.metadata, k.V1ObjectMeta)
            self._scope_metadata(cm_metadata, cm_metadata, pod_uid=pod_uid)

            config_map = k.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=cm_metadata,
                data=i_config_map.data,
                binary_data=i_config_map.binary_data,
                immutable=i_config_map.immutable,
            )

            assert cm_metadata.namespace and cm_metadata.name

            remote_config_map: k.V1ConfigMap = self._k_core_client.create_namespaced_config_map(
                namespace=cm_metadata.namespace, body=config_map
            )

            self.logger.info("ConfigMap '%s' in '%s' created", cm_metadata.name, cm_metadata.namespace)
            results.append(remote_config_map)
        return results

    def _create_secrets(self, i_secrets: list[i.Secret], *, pod_uid: str) -> list[k.V1Secret]:
        results = []

        for i_secret in i_secrets:
            secret_metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_secret.metadata, k.V1ObjectMeta)
            self._scope_metadata(secret_metadata, secret_metadata, pod_uid=pod_uid)

            secret = k.V1Secret(
                api_version="v1",
                kind="Secret",
                metadata=secret_metadata,
                data=i_secret.data,
                string_data=i_secret.string_data,
                immutable=i_secret.immutable,
                type=i_secret.type,
            )

            assert secret_metadata.namespace and secret_metadata.name

            remote_secret: k.V1Secret = self._k_core_client.create_namespaced_secret(
                namespace=secret_metadata.namespace, body=secret
            )

            self.logger.info("Secret '%s' in '%s' created", secret_metadata.name, secret_metadata.namespace)
            results.append(remote_secret)
        return results

    def _create_pvcs(
        self, i_pvcs: list[i.PersistentVolumeClaim], *, pod_uid: str, pod_metadata: i.Metadata
    ) -> list[k.V1PersistentVolumeClaim]:
        results = []

        for i_pvc in i_pvcs:
            assert i_pvc.metadata.name
            if not self._check_annotation_value(pod_metadata.annotations, _I_RMT_PVC_KEY, i_pvc.metadata.name):
                continue

            pvc_metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_pvc.metadata, k.V1ObjectMeta)
            self._scope_metadata(pvc_metadata, pvc_metadata, pod_uid=pod_uid, scope_name_by_pod_uid=False)
            pvc_spec = mappers.map_i_model_to_k_model(self._k_api_client, i_pvc.spec, k.V1PersistentVolumeClaimSpec)

            assert pvc_metadata.name and pvc_metadata.namespace

            if self._find_namespaced_pvc(pvc_metadata.name, pvc_metadata.namespace):
                self.logger.info(
                    "PVC '%s' in '%s' already exists, skip creation", pvc_metadata.name, pvc_metadata.namespace
                )
                continue

            pvc = k.V1PersistentVolumeClaim(
                api_version="v1",
                kind="PersistentVolumeClaim",
                metadata=pvc_metadata,
                spec=pvc_spec,
            )

            remote_pvc: k.V1PersistentVolumeClaim = self._k_core_client.create_namespaced_persistent_volume_claim(
                namespace=pvc_metadata.namespace, body=pvc
            )

            self.logger.info("PVC '%s' in '%s' created", pvc_metadata.name, pvc_metadata.namespace)
            results.append(remote_pvc)
        return results

    def _find_namespaced_pvc(self, pvc_name: str, pvc_namespace: str) -> k.V1PersistentVolumeClaim | None:
        """Find a PVC by name and namespace"""
        remote_pvcs: k.V1PersistentVolumeClaimList = self._k_core_client.list_namespaced_persistent_volume_claim(
            namespace=pvc_namespace
        )
        return _.find(
            remote_pvcs.items,
            lambda remote_pvc: (remote_pvc.metadata.name == pvc_name if remote_pvc.metadata else False),
        )

    def _check_annotation_value(self, annotations: dict[str, str] | None, key: str, value: str) -> bool:
        if annotations and key in annotations:
            values = annotations[key].split(",")
            return value in values
        return False

    def _get_container_ports(self, pod: k.V1Pod | i.PodRequest) -> list[int]:
        assert pod.spec

        container_ports = set()

        for c in pod.spec.containers or []:
            for port in c.ports or []:
                container_port = port.container_port
                if container_port and (port.protocol is None or port.protocol.upper() == "TCP"):
                    container_ports.add(container_port)

        return list(container_ports)

    def _filter_volumes(self, pod_spec: k.V1PodSpec, metadata: k.V1ObjectMeta, *, pod_uid: str):
        """Keep only supported volume types and scope their names"""
        # region spec.volumes
        filtered_volumes: list[k.V1Volume] = []
        for volume in pod_spec.volumes or []:
            if isinstance(volume, k.V1Volume):
                if volume.config_map:
                    assert volume.config_map.name
                    volume.config_map.name = self._scope_obj_name(volume.config_map.name, pod_uid=pod_uid)
                    filtered_volumes.append(volume)
                if volume.secret:
                    assert volume.secret.secret_name
                    volume.secret.secret_name = self._scope_obj_name(volume.secret.secret_name, pod_uid=pod_uid)
                    filtered_volumes.append(volume)
                if volume.empty_dir:
                    filtered_volumes.append(volume)
                if volume.persistent_volume_claim and self._check_annotation_value(
                    metadata.annotations, _I_RMT_PVC_KEY, volume.persistent_volume_claim.claim_name
                ):
                    filtered_volumes.append(volume)
        pod_spec.volumes = filtered_volumes or None
        # endregion
        # region spec.containers[*].volumeMounts
        for containers in [pod_spec.containers, pod_spec.init_containers]:
            if containers:
                for container in containers:
                    filtered_volume_mounts: list[k.V1VolumeMount] = []
                    for vm in container.volume_mounts or []:
                        # if _.find(scoped_volumes, lambda v, _idx, _coll, vm=vm: v.name == vm.name):
                        if next((fv for fv in filtered_volumes if fv.name == vm.name), None):
                            filtered_volume_mounts.append(vm)
                    container.volume_mounts = filtered_volume_mounts or None
        # endregion
        # region spec.containers[*].env[*].value_from, spec.containers[*].env_from
        for containers in [pod_spec.containers, pod_spec.init_containers]:
            if containers:
                for container in containers:
                    for env_var in container.env or []:
                        if value_from := env_var.value_from:
                            if value_from.config_map_key_ref and value_from.config_map_key_ref.name:
                                value_from.config_map_key_ref.name = self._scope_obj_name(
                                    value_from.config_map_key_ref.name, pod_uid=pod_uid
                                )
                            if value_from.secret_key_ref and value_from.secret_key_ref.name:
                                value_from.secret_key_ref.name = self._scope_obj_name(
                                    value_from.secret_key_ref.name, pod_uid=pod_uid
                                )
                    for env_from in container.env_from or []:
                        if env_from.config_map_ref and env_from.config_map_ref.name:
                            env_from.config_map_ref.name = self._scope_obj_name(
                                env_from.config_map_ref.name, pod_uid=pod_uid
                            )
                        if env_from.secret_ref and env_from.secret_ref.name:
                            env_from.secret_ref.name = self._scope_obj_name(env_from.secret_ref.name, pod_uid=pod_uid)
        # endregion

    def _scope_ns_name(self, name: str) -> str:
        """Scope a K8s namespace name to the configuration option `offloading.namespace_prefix`,
        provided it is not in the exclusion list"""
        return (
            f"{self._offloading_params["namespace_prefix"]}-{name}"
            if self._offloading_params["namespace_prefix"]
            and name not in self._offloading_params["namespace_prefix_exclusions"]
            else name
        )

    def _scope_obj_name(self, name: str, *, pod_uid: str) -> str:
        """Scope a K8s object name to the related Pod's uid"""
        return f"{name}-{pod_uid}"[:_MAX_K8S_SEGMENT_NAME] if pod_uid else name

    def _scope_bastion_rel_name(self, port: int, *, pod_uid: str) -> str:
        return f"bastion-{port}-{pod_uid}"[:_MAX_HELM_RELEASE_NAME]

    def _scope_metadata(
        self,
        metadata: k.V1ObjectMeta,
        source_metadata: k.V1ObjectMeta,
        *,
        pod_uid: str,
        scope_namespace: bool = True,
        scope_name_by_pod_uid: bool = True,
    ):
        assert metadata.annotations is not None and metadata.labels is not None
        assert source_metadata.uid and source_metadata.name and source_metadata.namespace

        metadata.labels.update({**_I_COMMON_LABELS, _I_SRC_POD_UID_KEY: pod_uid})
        metadata.annotations.update(
            {
                _I_SRC_UID_KEY: source_metadata.uid,
                _I_SRC_NAME_KEY: source_metadata.name,
                _I_SRC_NS_KEY: source_metadata.namespace,
            }
        )
        metadata.namespace = (
            self._scope_ns_name(source_metadata.namespace) if scope_namespace else source_metadata.namespace
        )
        metadata.name = (
            self._scope_obj_name(source_metadata.name, pod_uid=pod_uid)
            if scope_name_by_pod_uid
            else source_metadata.name
        )
