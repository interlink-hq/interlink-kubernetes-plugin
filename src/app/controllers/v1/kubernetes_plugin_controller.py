from http import HTTPStatus
from typing import Any

import interlink as i
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from fastapi_router_controller import Controller

from app.controllers.common.dto import ApiErrorResponseDto
from app.dependencies import get_kubernetes_plugin_service
from app.services.kubernetes_plugin_service import KubernetesPluginService

router = APIRouter()  # APIRouter(prefix="/api/v1/pod", tags=["V1Pod"])
controller = Controller(router, openapi_tag={"name": "Kubernetes Plugin Controller Api"})

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    # 401
    str(HTTPStatus.UNAUTHORIZED.value): {
        "model": ApiErrorResponseDto,
        "description": HTTPStatus.UNAUTHORIZED.phrase,
    },
    # 403
    str(HTTPStatus.FORBIDDEN.value): {
        "model": ApiErrorResponseDto,
        "description": HTTPStatus.FORBIDDEN.phrase,
    },
    # 422 - raised by Pydantic on validation error
    str(HTTPStatus.UNPROCESSABLE_ENTITY.value): {
        "model": ApiErrorResponseDto,
        "description": HTTPStatus.UNPROCESSABLE_ENTITY.phrase,
    },
    # 500
    str(HTTPStatus.INTERNAL_SERVER_ERROR.value): {
        "model": ApiErrorResponseDto,
        "description": HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
    },
}


@controller.use()
@controller.resource()
class KubernetesPluginController:
    @controller.route.get(
        "/status", summary="Get status", response_model_by_alias=True, responses=COMMON_ERROR_RESPONSES
    )
    async def get_status(
        self,
        i_pods: list[i.PodRequest],
        k_service: KubernetesPluginService = Depends(get_kubernetes_plugin_service),
    ) -> list[i.PodStatus]:
        return await k_service.get_status(i_pods)

    @controller.route.get("/getLogs", summary="Get logs", responses=COMMON_ERROR_RESPONSES)
    async def get_logs(
        self,
        i_log_req: i.LogRequest,
        k_service: KubernetesPluginService = Depends(get_kubernetes_plugin_service),
    ) -> PlainTextResponse:
        return PlainTextResponse(await k_service.get_logs(i_log_req))

    @controller.route.post(
        "/create", summary="Create Pod", response_model_by_alias=True, responses=COMMON_ERROR_RESPONSES
    )
    async def create_pod(
        self,
        i_pod_with_volumes: i.Pod,
        k_service: KubernetesPluginService = Depends(get_kubernetes_plugin_service),
    ) -> i.CreateStruct:
        return await k_service.create_pod(i_pod_with_volumes)

    @controller.route.post("/delete", summary="Delete Pod", responses=COMMON_ERROR_RESPONSES)
    async def delete_pod(
        self,
        i_pod: i.PodRequest,
        k_service: KubernetesPluginService = Depends(get_kubernetes_plugin_service),
    ) -> str:
        return await k_service.delete_pod(i_pod)
