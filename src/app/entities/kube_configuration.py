from kubernetes import client as k
from pydantic import BaseModel, ConfigDict


class KubeConfiguration(BaseModel):
    kubeconfig_path: str
    client_configuration: k.Configuration  # type: ignore

    model_config = ConfigDict(arbitrary_types_allowed=True)
