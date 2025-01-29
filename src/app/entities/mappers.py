from typing import Any, TypeVar

import kubernetes.client.api_client as k_api_client
from pydantic import BaseModel

KApiClient = k_api_client.ApiClient

T = TypeVar("T")


def serialize_k_model_to_dict(api_client: KApiClient, model: Any) -> dict:
    """Converts a Kubernetes model (i.e., OpenAPI model) to dict representation.
    Attribute names are mapped from snake_case to camelCase."""
    return api_client.sanitize_for_serialization(model)


def deserialize_dict_to_k_model(api_client: KApiClient, data: dict, k_ref_type: type[T]) -> T:
    """Converts a dict or list to a Kubernetes model.
    Expects property names in camelCase, they will be converted to snake_case.
    """
    # Notice that the protected function provided by ApiClient creates Kubernetes
    # objects recursively, while the following won't work for nested properties:
    # pod = V1Pod(**dict_to_snake(data))
    # type(pod.spec) == dict  # we don't get V1PodSpec
    return api_client._ApiClient__deserialize_model(data, k_ref_type)  # type: ignore # pylint: disable=protected-access


def map_i_model_to_k_model(api_client: KApiClient, model: BaseModel, k_ref_type: type[T]) -> T:
    """Converts an Interlink model to a Kubernetes (OpenAPI) model"""
    return deserialize_dict_to_k_model(api_client, model.model_dump(exclude_none=True, by_alias=True), k_ref_type)


def map_k_model_to_i_model(api_client: KApiClient, model: Any, i_ref_type: type[T]) -> T:
    """Converts a Kubernetes (OpenAPI) model to an Interlink model"""
    dikt = serialize_k_model_to_dict(api_client, model.to_dict())
    return i_ref_type(**dikt)
