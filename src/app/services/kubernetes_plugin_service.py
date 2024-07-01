from typing import List
from logging import Logger
import interlink

from injector import inject
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.api import CoreV1Api

from app.common.config import Config, Option

from .base_service import BaseService


class KubernetesPluginService(BaseService):

    _core_api: CoreV1Api

    @inject
    def __init__(self, config: Config, logger: Logger):
        super().__init__(config, logger)
        k8s_config.load_kube_config(config_file=config.get(Option.K8S_KUBECONFIG_PATH))
        self._core_api = k8s_client.CoreV1Api()

    async def get_status(self, pods: List[interlink.PodRequest]) -> List[interlink.PodStatus]:
        return []

    async def get_logs(self, req: interlink.LogRequest) -> bytes:
        return None

    async def create_pods(self, pods: List[interlink.Pod]) -> str:
        return ""

    async def delete_pod(self, pod: interlink.PodRequest) -> str:
        return ""
