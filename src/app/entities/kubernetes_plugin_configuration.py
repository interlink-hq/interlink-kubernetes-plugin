from kubernetes.client.configuration import Configuration as KClientConfiguration
from pydantic import BaseModel, ConfigDict


class KubernetesPluginConfiguration(BaseModel):
    kubeconfig_path: str
    client_configuration: KClientConfiguration | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
