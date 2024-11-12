import json
import subprocess
from logging import Logger
from typing import Any, Dict, Final, List

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

_I_SRC_UID_KEY: Final = "interlink/source.uid"
_I_SRC_POD_UID_KEY: Final = "interlink/source.pod_uid"
_I_SRC_NAME_KEY: Final = "interlink/source.name"
_I_SRC_NS_KEY: Final = "interlink/source.namespace"
_I_COMMON_LABELS: Final = {"interlink": "offloading"}

_MAX_K8S_SEGMENT_NAME: Final = 63
_MAX_HELM_RELEASE_NAME: Final = 53

_INSTALL_WITH_PYHELM_CLIENT: Final = False


class KubernetesPluginService(BaseService):

    _k_api: CoreV1Api
    _k_api_client: ApiClient
    _h_client: HelmClient
    _offloading_params: Dict[str, Any]

    @inject
    def __init__(self, config: Config, logger: Logger, k_api: k.CoreV1Api, h_client: HelmClient):
        super().__init__(config, logger)
        self._k_api = k_api
        self._k_api_client = k_api.api_client  # type: ignore
        self._h_client = h_client
        self._offloading_params = {
            "namespace": config.get(Option.OFFLOADING_NAMESPACE_PREFIX),
            "node_selector": json.loads(config.get(Option.OFFLOADING_NODE_SELECTOR, "null")),
            "node_tolerations": json.loads(config.get(Option.OFFLOADING_NODE_TOLERATIONS, "null")),
        }

    async def get_status(self, i_pods: List[i.PodRequest]) -> List[i.PodStatus]:
        status: List[i.PodStatus] = []
        for i_pod in i_pods:
            try:
                assert i_pod.metadata.name and i_pod.metadata.namespace and i_pod.metadata.uid

                remote_pod: k.V1Pod = self._k_api.read_namespaced_pod_status(
                    name=self._scope_obj(i_pod.metadata.name, pod_uid=i_pod.metadata.uid),
                    namespace=self._scope_ns(i_pod.metadata.namespace),
                )

                assert remote_pod.metadata and remote_pod.status

                remote_container_statuses: List[k.V1ContainerStatus] = remote_pod.status.container_statuses or []
                i_container_statuses: List[i.ContainerStatus] = []
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
        return self._k_api.read_namespaced_pod_log(
            name=self._scope_obj(i_log_req.pod_name, pod_uid=i_log_req.pod_uid),
            namespace=self._scope_ns(i_log_req.namespace),
            timestamps=i_log_req.opts.timestamps,
            previous=i_log_req.opts.previous,
            tail_lines=i_log_req.opts.tail or None,
            limit_bytes=i_log_req.opts.limit_bytes or None,
            since_seconds=i_log_req.opts.since_seconds or None,
        )

    async def create_pods(self, i_pods_with_volumes: List[i.Pod]) -> i.CreateStruct:
        results: List[i.CreateStruct] = []

        for i_pod_with_volumes in i_pods_with_volumes:
            try:
                # create namespace
                assert i_pod_with_volumes.pod.metadata.namespace
                self._create_offloading_namespace(i_pod_with_volumes.pod.metadata.namespace)

                # create supported volumes
                for i_volume in i_pod_with_volumes.container:
                    assert i_pod_with_volumes.pod.metadata.uid
                    if i_volume.config_maps:
                        self._create_config_maps(i_volume.config_maps, pod_uid=i_pod_with_volumes.pod.metadata.uid)
                    if i_volume.secrets:
                        self._create_secrets(i_volume.secrets, pod_uid=i_pod_with_volumes.pod.metadata.uid)

                # create pod
                results.append(await self._create_pod_and_bastion(i_pod_with_volumes.pod))
            except Exception as exc:
                await self.delete_pod(i_pod_with_volumes.pod, rollback=True)
                raise exc

        return results[0]

    async def delete_pod(self, i_pod: i.PodRequest, rollback=False) -> str:
        assert i_pod.metadata.uid and i_pod.metadata.name and i_pod.metadata.namespace

        name = self._scope_obj(i_pod.metadata.name, pod_uid=i_pod.metadata.uid)
        namespace = self._scope_ns(i_pod.metadata.namespace)

        if not rollback:
            self.logger.info("Delete Pod '%s' in '%s'", name, namespace)
        try:
            self._k_api.delete_namespaced_pod(name=name, namespace=namespace)
        except k_exceptions.ApiException as api_exception:
            if not rollback:
                self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")

        await self._install_bastion_release(i_pod, uninstall=True, rollback=rollback)

        if i_pod.spec and i_pod.spec.volumes:
            for volume in i_pod.spec.volumes:
                if volume.config_map:
                    scoped_name = self._scope_obj(volume.config_map.name, pod_uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete ConfigMap '%s' in '%s'", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_config_map(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
                if volume.secret:
                    scoped_name = self._scope_obj(volume.secret.secret_name, pod_uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete Secret '%s' in '%s'", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_secret(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")

        return f"Pod '{i_pod.metadata.uid}' deleted"

    def _create_offloading_namespace(self, name: str):
        scoped_ns = self._scope_ns(name)
        namespaces: k.V1NamespaceList = self._k_api.list_namespace(
            label_selector=",".join([f"{key}={value}" for key, value in _I_COMMON_LABELS.items()])
        )
        assert isinstance(namespaces.items, list)
        if _.find(namespaces.items, lambda item: item.metadata.name == scoped_ns if item.metadata else False):
            self.logger.info("Namespace '%s' already exists", scoped_ns)
        else:
            self._k_api.create_namespace(
                k.V1Namespace(
                    api_version="v1",
                    kind="Namespace",
                    metadata=k.V1ObjectMeta(name=scoped_ns, labels=_I_COMMON_LABELS),
                )
            )
            self.logger.info("Namespace '%s' created", scoped_ns)

    async def _create_pod_and_bastion(self, i_pod: i.PodRequest) -> i.CreateStruct:
        assert i_pod.metadata.uid

        metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.metadata, k.V1ObjectMeta)
        self._scope_metadata(metadata, metadata, pod_uid=i_pod.metadata.uid)

        pod_spec = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.spec, k.V1PodSpec)
        self._scope_volumes_and_config_maps(pod_spec, pod_uid=i_pod.metadata.uid)

        if self._offloading_params["node_selector"]:
            pod_spec.node_selector = self._offloading_params["node_selector"]
        if self._offloading_params["node_tolerations"]:
            pod_spec.tolerations = [k.V1Toleration(**t) for t in self._offloading_params["node_tolerations"]]

        pod = k.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=metadata,
            spec=pod_spec,
        )

        assert metadata.name and metadata.namespace

        remote_pod: k.V1Pod = self._k_api.create_namespaced_pod(namespace=metadata.namespace, body=pod)
        await self._install_bastion_release(i_pod)

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

        pod_name = self._scope_obj(i_pod.metadata.name, pod_uid=i_pod.metadata.uid)
        pod_ns = self._scope_ns(i_pod.metadata.namespace)
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
                    self._k_api.delete_namespaced_service(pod_name, pod_ns)
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
                self._k_api.create_namespaced_service(pod_ns, service)

                bastion_chart = await self._h_client.get_chart(self.config.get(Option.TCP_TUNNEL_BASTION_CHART_PATH))
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
                    command = f"""helm install {bastion_rel_name} infr/charts/tcp-tunnel/charts/bastion \
                        --kubeconfig {self.config.get(Option.K8S_KUBECONFIG_PATH)} \
                        --namespace tcp-tunnel --create-namespace \
                        --set tunnel.gateway.host={values["tunnel.gateway.host"]} \
                        --set tunnel.gateway.port={values["tunnel.gateway.port"]} \
                        --set tunnel.gateway.ssh.privateKey={values["tunnel.gateway.ssh.privateKey"]} \
                        --set tunnel.service.gatewayPort={values["tunnel.service.gatewayPort"]} \
                        --set tunnel.service.targetHost={values["tunnel.service.targetHost"]} \
                        --set tunnel.service.targetPort={values["tunnel.service.targetPort"]}""".split()
                    result = subprocess.run(
                        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
                    )
                    self.logger.debug(result.stdout)
            # endregion / install

    def _create_config_maps(self, i_config_maps: List[i.ConfigMap], *, pod_uid: str) -> List[k.V1ConfigMap]:
        results = []

        for i_config_map in i_config_maps:
            metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_config_map.metadata, k.V1ObjectMeta)
            self._scope_metadata(metadata, metadata, pod_uid=pod_uid)

            config_map = k.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=metadata,
                data=i_config_map.data,
                binary_data=i_config_map.binary_data,
                immutable=i_config_map.immutable,
            )

            assert metadata.namespace and metadata.name

            remote_config_map: k.V1ConfigMap = self._k_api.create_namespaced_config_map(
                namespace=metadata.namespace, body=config_map
            )

            self.logger.info("ConfigMap '%s' in '%s' created", metadata.name, metadata.namespace)
            results.append(remote_config_map)
        return results

    def _create_secrets(self, i_secrets: List[i.Secret], *, pod_uid: str) -> List[k.V1Secret]:
        results = []

        for i_secret in i_secrets:
            metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_secret.metadata, k.V1ObjectMeta)
            self._scope_metadata(metadata, metadata, pod_uid=pod_uid)

            secret = k.V1Secret(
                api_version="v1",
                kind="Secret",
                metadata=metadata,
                data=i_secret.data,
                string_data=i_secret.string_data,
                immutable=i_secret.immutable,
                type=i_secret.type,
            )

            assert metadata.namespace and metadata.name

            remote_secret: k.V1Secret = self._k_api.create_namespaced_secret(namespace=metadata.namespace, body=secret)

            self.logger.info("Secret '%s' in '%s' created", metadata.name, metadata.namespace)
            results.append(remote_secret)
        return results

    def _get_container_ports(self, pod: k.V1Pod | i.PodRequest) -> List[int]:
        assert pod.spec

        container_ports = set()

        for c in pod.spec.containers or []:
            for port in c.ports or []:
                container_port = port.container_port
                if container_port and (port.protocol is None or port.protocol.upper() == "TCP"):
                    container_ports.add(container_port)

        return list(container_ports)

    def _scope_ns(self, name: str) -> str:
        """Scope a K8s namespace name to the configuration option `k8s.offloading_namespace`"""
        return f"{self._offloading_params["namespace"]}-{name}" if self._offloading_params["namespace"] else name

    def _scope_obj(self, name: str, *, pod_uid: str) -> str:
        """Scope a K8s object name to the related Pod's uid"""
        return f"{name}-{pod_uid}"[:_MAX_K8S_SEGMENT_NAME] if pod_uid else name

    def _scope_bastion_rel_name(self, port: int, *, pod_uid: str) -> str:
        return f"bastion-{port}-{pod_uid}"[:_MAX_HELM_RELEASE_NAME]

    def _scope_metadata(self, metadata: k.V1ObjectMeta, source_metadata: k.V1ObjectMeta, *, pod_uid: str):
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
        metadata.namespace = self._scope_ns(source_metadata.namespace)
        metadata.name = self._scope_obj(source_metadata.name, pod_uid=pod_uid)

    def _scope_volumes_and_config_maps(self, pod_spec: k.V1PodSpec, *, pod_uid: str):
        # region spec.volumes
        scoped_volumes: List[k.V1Volume] = []
        for volume in pod_spec.volumes or []:
            if isinstance(volume, k.V1Volume):
                if volume.config_map:
                    assert volume.config_map.name
                    volume.config_map.name = self._scope_obj(volume.config_map.name, pod_uid=pod_uid)
                    scoped_volumes.append(volume)
                if volume.secret:
                    assert volume.secret.secret_name
                    volume.secret.secret_name = self._scope_obj(volume.secret.secret_name, pod_uid=pod_uid)
                    scoped_volumes.append(volume)
                if volume.empty_dir:
                    scoped_volumes.append(volume)
        pod_spec.volumes = scoped_volumes or None
        # endregion
        # region spec.containers[*].volumeMounts
        for container in pod_spec.containers:
            scoped_volume_mounts: List[k.V1VolumeMount] = []
            for vm in container.volume_mounts or []:
                # if _.find(scoped_volumes, lambda v, _idx, _coll, vm=vm: v.name == vm.name):
                if next((v for v in scoped_volumes if v.name == vm.name), None):
                    scoped_volume_mounts.append(vm)
            container.volume_mounts = scoped_volume_mounts or None
        # endregion
        # region spec.containers[*].env[*].value_from, spec.containers[*].env_from
        for container in pod_spec.containers:
            for env_var in container.env or []:
                if value_from := env_var.value_from:
                    if value_from.config_map_key_ref and value_from.config_map_key_ref.name:
                        value_from.config_map_key_ref.name = self._scope_obj(
                            value_from.config_map_key_ref.name, pod_uid=pod_uid
                        )
                    if value_from.secret_key_ref and value_from.secret_key_ref.name:
                        value_from.secret_key_ref.name = self._scope_obj(
                            value_from.secret_key_ref.name, pod_uid=pod_uid
                        )
            for env_from in container.env_from or []:
                if env_from.config_map_ref and env_from.config_map_ref.name:
                    env_from.config_map_ref.name = self._scope_obj(env_from.config_map_ref.name, pod_uid=pod_uid)
                if env_from.secret_ref and env_from.secret_ref.name:
                    env_from.secret_ref.name = self._scope_obj(env_from.secret_ref.name, pod_uid=pod_uid)
        # endregion
