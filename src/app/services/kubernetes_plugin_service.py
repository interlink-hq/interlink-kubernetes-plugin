from logging import Logger
from typing import List

import interlink as i
import kubernetes.client.exceptions as k_exceptions
import pydash as _
from injector import inject
from kubernetes import client as k
from kubernetes.client.api import CoreV1Api
from kubernetes.client.api_client import ApiClient

from app.common.config import Config, Option
from app.entities import mappers

from .base_service import BaseService

_I_S_UID_ANN_KEY = "interlink/source.uid"
_I_S_NAME_ANN_KEY = "interlink/source.name"
_I_S_NS_ANN_KEY = "interlink/source.namespace"
_I_LABELS = {"interlink": "offloading"}
_I_LABELS_SELECTOR = ",".join([f"{key}={value}" for key, value in _I_LABELS.items()])


class KubernetesPluginService(BaseService):

    _k_api: CoreV1Api
    _k_api_client: ApiClient
    _offloading_namespace: str

    @inject
    def __init__(self, config: Config, logger: Logger, k_api: k.CoreV1Api):
        super().__init__(config, logger)
        self._k_api = k_api
        self._k_api_client = k_api.api_client  # type: ignore
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

                self.logger.debug(
                    "Pod '%s' (namespace '%s') status: %s",
                    remote_pod.metadata.name,
                    remote_pod.metadata.namespace,
                    str(i_pod_status.containers),
                )
            except k_exceptions.ApiException as api_exception:
                raise api_exception
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
                assert i_pod_with_volumes.pod.metadata.namespace
                self._create_offloading_namespace(i_pod_with_volumes.pod.metadata.namespace)

                for i_volume in i_pod_with_volumes.container:
                    if i_volume.configMaps:
                        self._create_config_maps(i_volume.configMaps, uid=i_pod_with_volumes.pod.metadata.uid)
                    if i_volume.secrets:
                        self._create_secrets(i_volume.secrets, uid=i_pod_with_volumes.pod.metadata.uid)
                results.append(self._create_pod(i_pod_with_volumes.pod))
            except k_exceptions.ApiException as api_exception:
                raise api_exception

        return results[0]

    async def delete_pod(self, i_pod: i.PodRequest) -> str:
        assert i_pod.metadata.name and i_pod.metadata.namespace

        name = self._scoped_obj(i_pod.metadata.name, uid=i_pod.metadata.uid)
        namespace = self._scoped_ns(i_pod.metadata.namespace)
        self.logger.info("Delete Pod '%s' (namespace '%s')", name, namespace)

        try:
            self._k_api.delete_namespaced_pod(name=name, namespace=namespace)
        except k_exceptions.ApiException as api_exception:
            self.logger.error(api_exception)

        if i_pod.spec and i_pod.spec.volumes:
            for volume in i_pod.spec.volumes:
                if volume.configMap:
                    scoped_name = self._scoped_obj(volume.configMap.name, uid=i_pod.metadata.uid)
                    self.logger.info("Delete ConfigMap '%s' (namespace '%s')", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_config_map(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        self.logger.error(api_exception)
                if volume.secret:
                    scoped_name = self._scoped_obj(volume.secret.secretName, uid=i_pod.metadata.uid)
                    self.logger.info("Delete Secret '%s' (namespace '%s')", scoped_name, namespace)
                    try:
                        self._k_api.delete_namespaced_secret(scoped_name, namespace)
                    except k_exceptions.ApiException as api_exception:
                        self.logger.error(api_exception)

        return "Pod deleted"

    def _create_offloading_namespace(self, name: str):
        scoped_ns = self._scoped_ns(name)
        namespaces: k.V1NamespaceList = self._k_api.list_namespace(label_selector=_I_LABELS_SELECTOR)
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

    def _create_pod(self, i_pod: i.PodRequest) -> i.CreateStruct:
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

        assert metadata.namespace
        assert pod.spec

        remote_pod: k.V1Pod = self._k_api.create_namespaced_pod(namespace=metadata.namespace, body=pod)

        assert i_pod.metadata.uid and remote_pod.metadata and remote_pod.metadata.uid

        create_result = i.CreateStruct(PodUID=i_pod.metadata.uid, PodJID=remote_pod.metadata.uid)
        self.logger.info(
            "Pod '%s' (namespace '%s') created, with result: %s",
            remote_pod.metadata.name,
            remote_pod.metadata.namespace,
            create_result,
        )
        return create_result

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

            self.logger.info("ConfigMap '%s' (namespace '%s') created", metadata.name, metadata.namespace)
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

            self.logger.info("Secret '%s' (namespace '%s') created", metadata.name, metadata.namespace)
            results.append(remote_secret)
        return results

    def _scoped_ns(self, name: str) -> str:
        """Scope a namespace name to the configuration option `_offloading_namespace`"""
        return f"{self._offloading_namespace}-{name}" if self._offloading_namespace else name

    def _scoped_obj(self, name: str, *, uid: str | None) -> str:
        """Scope an object name to the related Pod's uid"""
        return f"{name}-{uid}" if uid else name

    def _scoped_metadata(self, metadata: k.V1ObjectMeta, source_metadata: k.V1ObjectMeta, *, uid: str | None):
        assert metadata.annotations is not None and metadata.labels is not None
        assert source_metadata.uid and source_metadata.name and source_metadata.namespace

        metadata.labels.update(_I_LABELS)
        metadata.annotations.update(
            {
                _I_S_UID_ANN_KEY: source_metadata.uid,
                _I_S_NAME_ANN_KEY: source_metadata.name,
                _I_S_NS_ANN_KEY: source_metadata.namespace,
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
