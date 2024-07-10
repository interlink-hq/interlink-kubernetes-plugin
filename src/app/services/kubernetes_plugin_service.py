from logging import Logger
from typing import Dict, List

import interlink
import pydash as _
from injector import inject
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.api import CoreV1Api

from app.common.config import Config, Option
from app.utilities.dictionary_utilities import map_key_names, map_datetime_to_str

from .base_service import BaseService


_IK_UID_ANNOTATION_KEY = "interlink/uid"


class KubernetesPluginService(BaseService):

    _core_api: CoreV1Api

    @inject
    def __init__(self, config: Config, logger: Logger):
        super().__init__(config, logger)
        k8s_config.load_kube_config(config_file=config.get(Option.K8S_KUBECONFIG_PATH))
        self._core_api = client.CoreV1Api()

    async def get_status(self, pods: List[interlink.PodRequest]) -> List[interlink.PodStatus]:
        status: List[interlink.PodStatus] = []
        for ik_pod_request in pods:
            try:
                remote_pod: client.V1Pod = self._core_api.read_namespaced_pod_status(
                    name=f"{ik_pod_request.metadata.name}-{ik_pod_request.metadata.uid}",
                    namespace=ik_pod_request.metadata.namespace,
                )  # type: ignore

                # region Type checking
                assert (
                    isinstance(remote_pod.metadata, client.V1ObjectMeta)
                    and remote_pod.metadata.name is not None
                    and remote_pod.metadata.namespace is not None
                )
                assert (
                    isinstance(remote_pod.metadata.annotations, Dict)
                    and _IK_UID_ANNOTATION_KEY in remote_pod.metadata.annotations
                )
                assert isinstance(remote_pod.status, client.V1PodStatus)
                assert isinstance(ik_pod_request.metadata.name, str) and isinstance(ik_pod_request.metadata.uid, str)
                # endregion / Type checking

                remote_container_statuses: List[client.V1ContainerStatus] = remote_pod.status.container_statuses  # type: ignore  # pylint: disable=line-too-long  # noqa: E501
                ik_container_statuses: List[interlink.ContainerStatus] = [
                    map_container_status(container_status) for container_status in remote_container_statuses
                ]

                pod_status = interlink.PodStatus(
                    name=ik_pod_request.metadata.name,
                    UID=ik_pod_request.metadata.uid,
                    namespace=remote_pod.metadata.namespace,
                    containers=ik_container_statuses,
                )

                status.append(pod_status)
                self.logger.info("Pod '%s' status='%s'", pod_status.name, pod_status.containers)
            except client.ApiException as api_exception:
                raise api_exception
        return status

    async def get_logs(self, req: interlink.LogRequest) -> str:
        return self._core_api.read_namespaced_pod_log(name=f"{req.PodName}-{req.PodUID}", namespace=req.Namespace)

    async def create_pods(self, pods: List[interlink.Pod]) -> interlink.CreateStruct:
        results = []

        for ik_pod in pods:
            try:
                pod = client.V1Pod(
                    api_version="v1",
                    kind="Pod",
                    metadata=map_ik_metadata(ik_pod.pod.metadata),
                    spec=map_ik_pod_spec(ik_pod.pod.spec),
                )

                # region Type checking
                assert isinstance(pod.metadata, client.V1ObjectMeta)
                assert isinstance(pod.spec, client.V1PodSpec)
                assert ik_pod.pod.metadata.uid is not None
                # endregion

                pod.metadata.name = f"{ik_pod.pod.metadata.name}-{ik_pod.pod.metadata.uid}"
                pod.metadata.annotations[_IK_UID_ANNOTATION_KEY] = ik_pod.pod.metadata.uid  # type: ignore

                remote_pod: client.V1Pod = self._core_api.create_namespaced_pod(
                    namespace=ik_pod.pod.metadata.namespace, body=pod
                )  # type: ignore

                # region Type checking
                assert remote_pod.metadata is not None
                assert isinstance(remote_pod.metadata.uid, str)
                # endregion

                create_result = interlink.CreateStruct(PodUID=ik_pod.pod.metadata.uid, PodJID=remote_pod.metadata.uid)
                self.logger.info("Pod '%s' created: '%s'", remote_pod.metadata.name, create_result)
                results.append(create_result)
            except client.ApiException as api_exception:
                raise api_exception

        return results[0]

    async def delete_pod(self, ik_pod_request: interlink.PodRequest) -> str:
        try:
            remote_pod: client.V1Pod = self._core_api.delete_namespaced_pod(
                name=f"{ik_pod_request.metadata.name}-{ik_pod_request.metadata.uid}",
                namespace=ik_pod_request.metadata.namespace,
            )  # type: ignore
            assert remote_pod.metadata is not None
            self.logger.info("Pod '%s' deleted, status='%s'", remote_pod.metadata.name, str(remote_pod.status))
        except client.ApiException as api_exception:
            raise api_exception
        return "Pod deleted"


def map_ik_metadata(ik_metadata: interlink.Metadata) -> client.V1ObjectMeta:
    return client.V1ObjectMeta(
        **map_key_names(ik_metadata.model_dump(), client.V1ObjectMeta.attribute_map, reverse=True)
    )


def map_ik_pod_spec(ik_pod_spec: interlink.PodSpec) -> client.V1PodSpec:
    return client.V1PodSpec(**map_key_names(ik_pod_spec.model_dump(), client.V1PodSpec.attribute_map, reverse=True))


def map_container_status(container_status: client.V1ContainerStatus) -> interlink.ContainerStatus:
    return interlink.ContainerStatus(
        **map_datetime_to_str(
            map_key_names(
                container_status.to_dict(),
                _.merge(
                    {},
                    client.V1ContainerStatus.attribute_map,
                    client.V1ContainerState.attribute_map,
                    client.V1ContainerStateRunning.attribute_map,
                    client.V1ContainerStateTerminated.attribute_map,
                    client.V1ContainerStateWaiting.attribute_map,
                ),
                deep=True,
            )
        )
    )
