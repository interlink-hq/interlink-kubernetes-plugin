from typing import Any, TypeVar
from kubernetes.client.api_client import ApiClient
from pydantic import BaseModel


T = TypeVar("T")


def serialize_k_model_to_dict(api_client: ApiClient, model: Any) -> dict:
    """Converts a Kubernetes model to dict or list representation.
    Attribute names are mapped from snake_case to camelCase."""
    return api_client.sanitize_for_serialization(model)


def deserialize_dict_to_k_model(api_client: ApiClient, data: dict, k_ref_type: type[T]) -> T:
    """Converts a dict or list to a Kubernetes model.
    Expects property names in camelCase that will be converted to snake_case.
    """
    # Notice that the protected function provided by ApiClient creates Kubernetes
    # objects recursively, while the following won't work for nested properties:
    # pod = V1Pod(**dict_to_snake(data))
    # type(pod.spec) == dict  # we don't get V1PodSpec
    return api_client._ApiClient__deserialize_model(data, k_ref_type)  # type: ignore # pylint: disable=protected-access


def map_i_model_to_k_model(api_client: ApiClient, model: BaseModel, k_ref_type: type[T]) -> T:
    """Converts an Interlink model to a Kubernetes model"""
    return deserialize_dict_to_k_model(api_client, model.model_dump(exclude_none=True, by_alias=True), k_ref_type)


def map_k_model_to_i_model(api_client: ApiClient, model: Any, i_ref_type: type[T]) -> T:
    """Converts a Kubernetes model to an Interlink model"""
    dikt = serialize_k_model_to_dict(api_client, model.to_dict())
    return i_ref_type(**dikt)
