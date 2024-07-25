from typing import Any, TypeVar
import interlink as i
import pydash as _
from kubernetes import client as k
from kubernetes.client.api_client import ApiClient
from pydantic import BaseModel

from app.utilities.dictionary_utilities import map_datetime_to_str, map_key_names


T = TypeVar("T")


def serialize_k_model_to_dict(api_client: ApiClient, model: Any) -> dict:
    """Converts a model to dict representation mapping attribute names from snake_case to camelCase"""
    return api_client.sanitize_for_serialization(model)


def deserialize_dict_to_k_model(api_client: ApiClient, data: dict, k_ref_type: type[T]) -> T:
    """Converts a list or dict to a model mapping attribute names from camelCase to snake_case"""
    return api_client._ApiClient__deserialize_model(data, k_ref_type)  # type: ignore # pylint: disable=protected-access


def map_i_model_to_k_model(api_client: ApiClient, model: BaseModel, k_ref_type: type[T]) -> T:
    """Converts an Interlink model to a Kubernetes model"""
    return deserialize_dict_to_k_model(api_client, model.model_dump(exclude_none=True), k_ref_type)


def map_k_model_to_i_model(api_client: ApiClient, obj: Any, i_ref_type: type[T]) -> T:
    """Converts a Kubernetes model to an Interlink model"""
    dikt = serialize_k_model_to_dict(api_client, obj.to_dict())
    return i_ref_type(**dikt)


def map_i_metadata(i_metadata: i.Metadata) -> k.V1ObjectMeta:
    return k.V1ObjectMeta(
        **map_key_names(i_metadata.model_dump(exclude_none=True), k.V1ObjectMeta.attribute_map, reverse=True)
    )


def map_i_pod_spec(i_pod_spec: i.PodSpec) -> k.V1PodSpec:
    return k.V1PodSpec(
        **map_key_names(
            i_pod_spec.model_dump(exclude_none=True),
            _.merge(
                {},
                k.V1PodSpec.attribute_map,
                k.V1Container.attribute_map,
                k.V1VolumeMount.attribute_map,
                k.V1EnvVar.attribute_map,
                k.V1EnvVarSource.attribute_map,
                k.V1Volume.attribute_map,
                k.V1SecretVolumeSource.attribute_map,
                k.V1ConfigMapVolumeSource.attribute_map,
            ),
            reverse=True,
            deep=True,
        )
    )


def map_k_container_status(container_status: k.V1ContainerStatus) -> i.ContainerStatus:
    return i.ContainerStatus(
        **map_datetime_to_str(
            map_key_names(
                container_status.to_dict(),
                _.merge(
                    {},
                    k.V1ContainerStatus.attribute_map,
                    k.V1ContainerState.attribute_map,
                    k.V1ContainerStateRunning.attribute_map,
                    k.V1ContainerStateTerminated.attribute_map,
                    k.V1ContainerStateWaiting.attribute_map,
                ),
                deep=True,
            )
        )
    )
