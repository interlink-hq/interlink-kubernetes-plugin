import subprocess
from logging import Logger
from typing import Final, List

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
_I_SRC_NAME_KEY: Final = "interlink/source.name"
_I_SRC_NS_KEY: Final = "interlink/source.namespace"
_I_LABELS: Final = {"interlink": "offloading"}

_MAX_K8S_SEGMENT_NAME: Final = 63
_MAX_HELM_RELEASE_NAME: Final = 53


class KubernetesPluginService(BaseService):

    _k_api: CoreV1Api
    _k_api_client: ApiClient
    _h_client: HelmClient
    _offloading_namespace: str

    @inject
    def __init__(self, config: Config, logger: Logger, k_api: k.CoreV1Api, h_client: HelmClient):
        super().__init__(config, logger)
        self._k_api = k_api
        self._k_api_client = k_api.api_client  # type: ignore
        self._h_client = h_client
        self._offloading_namespace = config.get(Option.K8S_OFFLOADING_NAMESPACE)

    async def get_status(self, i_pods: List[i.PodRequest]) -> List[i.PodStatus]:
        status: List[i.PodStatus] = []
        for i_pod in i_pods:
            try:
                assert i_pod.metadata.name and i_pod.metadata.namespace and i_pod.metadata.uid

                remote_pod: k.V1Pod = self._k_api.read_namespaced_pod_status(
                    name=self._scoped_obj(i_pod.metadata.name, uid=i_pod.metadata.uid),
                    namespace=self._scoped_ns(i_pod.metadata.namespace),
                )

                assert remote_pod.metadata and remote_pod.status

                remote_container_statuses: List[k.V1ContainerStatus] = remote_pod.status.container_statuses or []
                i_container_statuses: List[i.ContainerStatus] = [
                    mappers.map_k_model_to_i_model(self._k_api_client, cs, i.ContainerStatus)
                    for cs in remote_container_statuses
                ]

                i_pod_status = i.PodStatus(
                    UID=i_pod.metadata.uid,
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
        return self._k_api.read_namespaced_pod_log(
            name=self._scoped_obj(i_log_req.PodName, uid=i_log_req.PodUID),
            namespace=self._scoped_ns(i_log_req.Namespace),
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
                    if i_volume.configMaps:
                        self._create_config_maps(i_volume.configMaps, uid=i_pod_with_volumes.pod.metadata.uid)
                    if i_volume.secrets:
                        self._create_secrets(i_volume.secrets, uid=i_pod_with_volumes.pod.metadata.uid)

                # create pod
                results.append(await self._create_pod_and_bastion(i_pod_with_volumes.pod))
            except Exception as exc:
                await self.delete_pod(i_pod_with_volumes.pod, rollback=True)
                raise exc

        return results[0]

    async def delete_pod(self, i_pod: i.PodRequest, rollback=False) -> str:
        assert i_pod.metadata.name and i_pod.metadata.namespace

        name = self._scoped_obj(i_pod.metadata.name, uid=i_pod.metadata.uid)
        namespace = self._scoped_ns(i_pod.metadata.namespace)

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
                if volume.configMap:
                    scoped_name = self._scoped_obj(volume.configMap.name, uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete ConfigMap '%s' in '%s'", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_config_map(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
                if volume.secret:
                    scoped_name = self._scoped_obj(volume.secret.secretName, uid=i_pod.metadata.uid)
                    if not rollback:
                        self.logger.info("Delete Secret '%s' in '%s'", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_secret(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        if not rollback:
                            self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")

        return "Pod deleted"

    def _create_offloading_namespace(self, name: str):
        scoped_ns = self._scoped_ns(name)
        namespaces: k.V1NamespaceList = self._k_api.list_namespace(
            label_selector=",".join([f"{key}={value}" for key, value in _I_LABELS.items()])
        )
        assert isinstance(namespaces.items, list)
        if _.find(namespaces.items, lambda item: item.metadata.name == scoped_ns if item.metadata else False):
            self.logger.info("Namespace '%s' already exists", scoped_ns)
        else:
            self._k_api.create_namespace(
                k.V1Namespace(
                    api_version="v1",
                    kind="Namespace",
                    metadata=k.V1ObjectMeta(name=scoped_ns, labels=_I_LABELS),
                )
            )
            self.logger.info("Namespace '%s' created", scoped_ns)

    async def _create_pod_and_bastion(self, i_pod: i.PodRequest) -> i.CreateStruct:
        metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.metadata, k.V1ObjectMeta)
        self._scoped_metadata(metadata, metadata, uid=i_pod.metadata.uid)

        pod_spec = mappers.map_i_model_to_k_model(self._k_api_client, i_pod.spec, k.V1PodSpec)
        self._scoped_volumes(pod_spec, uid=i_pod.metadata.uid)

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

        create_result = i.CreateStruct(PodUID=i_pod.metadata.uid, PodJID=remote_pod.metadata.uid)
        self.logger.info(
            "Pod '%s' in '%s' created, with result: %s",
            remote_pod.metadata.name,
            remote_pod.metadata.namespace,
            create_result,
        )
        return create_result

    async def _install_bastion_release(self, i_pod: i.PodRequest, uninstall=False, rollback=False):
        """
        Install/uninstall Bastion release for the given `ProdRequest`.

        Raises:
            `HelmError`,
            `k_exceptions.ApiException`

        Note:
            if uninstall, exceptions are captured and not rethrown.
        """

        assert i_pod.metadata.name and i_pod.metadata.namespace and i_pod.metadata.uid

        name = self._scoped_obj(i_pod.metadata.name, uid=i_pod.metadata.uid)
        namespace = self._scoped_ns(i_pod.metadata.namespace)
        bastion_rel_ns = self.config.get(Option.TCP_TUNNEL_BASTION_NAMESPACE)

        ports = self._get_container_ports(i_pod)

        for port in ports:
            bastion_rel_name = self._scoped_bastion_rel_name(port, name)
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
                    self.logger.info("Delete Headless Service '%s' in '%s'", name, namespace)
                try:
                    self._k_api.delete_namespaced_service(name, namespace)
                except k_exceptions.ApiException as api_exception:
                    if not rollback:
                        self.logger.error(f"{api_exception.status} {api_exception.reason}: {api_exception.body}")
            # endregion / uninstall
            # region install
            else:
                self.logger.info("Create Headless Service '%s' in '%s'", name, namespace)
                service = k.V1Service(
                    metadata=k.V1ObjectMeta(name=name, namespace=namespace),
                    spec=k.V1ServiceSpec(
                        selector={
                            **_I_LABELS,
                            _I_SRC_UID_KEY: i_pod.metadata.uid,
                        },
                        cluster_ip="None",  # headless service
                        ports=[k.V1ServicePort(port=port, target_port=port)],
                    ),
                )
                self._k_api.create_namespaced_service(namespace, service)

                bastion_chart = await self._h_client.get_chart(self.config.get(Option.TCP_TUNNEL_BASTION_CHART_PATH))
                self.logger.info("Install release '%s' in '%s'", bastion_rel_name, bastion_rel_ns)
                values = {
                    "tunnel.gateway.host": self.config.get(Option.TCP_TUNNEL_GATEWAY_HOST),
                    "tunnel.gateway.ssh.privateKey": self.config.get(Option.TCP_TUNNEL_GATEWAY_SSH_PRIVATE_KEY),
                    "tunnel.service.gatewayPort": port,
                    "tunnel.service.targetPort": port,
                    "tunnel.service.targetHost": f"{name}.{namespace}.svc",
                }
                if 0 == 1:
                    # TODO not working
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
                        --set tunnel.gateway.ssh.privateKey={values["tunnel.gateway.ssh.privateKey"]} \
                        --set tunnel.service.gatewayPort={values["tunnel.service.gatewayPort"]} \
                        --set tunnel.service.targetHost={values["tunnel.service.targetHost"]} \
                        --set tunnel.service.targetPort={values["tunnel.service.targetPort"]}""".split()

                    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.logger.debug(result)
            # endregion / install

    def _create_config_maps(self, i_config_maps: List[i.ConfigMap], *, uid: str | None) -> List[k.V1ConfigMap]:
        results = []

        for i_config_map in i_config_maps:
            metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_config_map.metadata, k.V1ObjectMeta)
            self._scoped_metadata(metadata, metadata, uid=uid)

            config_map = k.V1ConfigMap(
                api_version="v1",
                kind="ConfigMap",
                metadata=metadata,
                data=i_config_map.data,
                binary_data=i_config_map.binaryData,
                immutable=i_config_map.immutable,
            )

            assert metadata.namespace and metadata.name

            remote_config_map: k.V1ConfigMap = self._k_api.create_namespaced_config_map(
                namespace=metadata.namespace, body=config_map
            )

            self.logger.info("ConfigMap '%s' in '%s' created", metadata.name, metadata.namespace)
            results.append(remote_config_map)
        return results

    def _create_secrets(self, i_secrets: List[i.Secret], *, uid: str | None) -> List[k.V1Secret]:
        results = []

        for i_secret in i_secrets:
            metadata = mappers.map_i_model_to_k_model(self._k_api_client, i_secret.metadata, k.V1ObjectMeta)
            self._scoped_metadata(metadata, metadata, uid=uid)

            secret = k.V1Secret(
                api_version="v1",
                kind="Secret",
                metadata=metadata,
                data=i_secret.data,
                string_data=i_secret.stringData,
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

        # TODO
        # for c in pod.spec.containers or []:
        #     for port in c.ports or []:
        #         if port.container_port and (port.protocol is None or port.protocol.upper() == "TCP"):
        #             container_ports.add(port.container_port)
        container_ports.add(8181)

        return list(container_ports)

    def _scoped_ns(self, name: str) -> str:
        """Scope a K8s namespace name to the configuration option `_offloading_namespace`"""
        return f"{self._offloading_namespace}-{name}" if self._offloading_namespace else name

    def _scoped_obj(self, name: str, *, uid: str | None) -> str:
        """Scope a K8s object name to the related Pod's uid"""
        return f"{name}-{uid}"[:_MAX_K8S_SEGMENT_NAME] if uid else name

    def _scoped_bastion_rel_name(self, port: int, pod_name: str) -> str:
        return f"bastion-{port}-{pod_name}"[:_MAX_HELM_RELEASE_NAME]

    def _scoped_metadata(self, metadata: k.V1ObjectMeta, source_metadata: k.V1ObjectMeta, *, uid: str | None):
        assert metadata.annotations is not None and metadata.labels is not None
        assert source_metadata.uid and source_metadata.name and source_metadata.namespace

        metadata.labels.update(
            {
                **_I_LABELS,
                _I_SRC_UID_KEY: source_metadata.uid,
            }
        )
        metadata.annotations.update(
            {
                _I_SRC_NAME_KEY: source_metadata.name,
                _I_SRC_NS_KEY: source_metadata.namespace,
            }
        )
        metadata.namespace = self._scoped_ns(source_metadata.namespace)
        if uid:
            metadata.name = self._scoped_obj(source_metadata.name, uid=uid)

    def _scoped_volumes(self, pod_spec: k.V1PodSpec, *, uid: str | None):
        # region spec.volumes
        scoped_volumes: List[k.V1Volume] = []
        for volume in pod_spec.volumes or []:
            if isinstance(volume, k.V1Volume):
                if volume.config_map:
                    assert volume.config_map.name
                    volume.config_map.name = self._scoped_obj(volume.config_map.name, uid=uid)
                    scoped_volumes.append(volume)
                if volume.secret:
                    assert volume.secret.secret_name
                    volume.secret.secret_name = self._scoped_obj(volume.secret.secret_name, uid=uid)
                    scoped_volumes.append(volume)
                if volume.empty_dir:
                    scoped_volumes.append(volume)
        pod_spec.volumes = scoped_volumes if scoped_volumes else None
        # endregion
        # region spec.containers[*].volumeMounts
        for container in pod_spec.containers:
            scoped_volume_mounts: List[k.V1VolumeMount] = []
            for volume_mount in container.volume_mounts or []:
                if _.find(scoped_volumes, lambda v: v.name == volume_mount.name):
                    scoped_volume_mounts.append(volume_mount)
            container.volume_mounts = scoped_volume_mounts if scoped_volume_mounts else None
        # endregion
