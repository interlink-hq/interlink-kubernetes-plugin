"""
FastAPI entry point: load controllers and start the app.
"""

from contextlib import asynccontextmanager
from http import HTTPStatus
from starlette.middleware.base import BaseHTTPMiddleware

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi_router_controller import Controller

from app.common.config import Option
from app.utilities.async_utilities import manage_contexts
from app.common.error_types import ApplicationError

from . import controllers
from .dependencies import get_config, get_lifespan_async_context_managers, get_logger

config = get_config()
logger = get_logger()

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with manage_contexts(get_lifespan_async_context_managers()):
        yield


app = FastAPI(
    lifespan=lifespan,
    title=config.get(Option.APP_NAME),
    description=config.get(Option.APP_DESCRIPTION),
    version=config.get(Option.APP_VERSION),
    docs_url=config.get(Option.API_DOCS_PATH),
    openapi_tags=[
        {
            "name": config.get(Option.APP_NAME),
            "description": config.get(Option.APP_DESCRIPTION),
        }
    ],
)


# region CORS Middleware
# _ALLOWED_ORIGINS: Final = [
#     "*",
#     "http://localhost",
#     "http://localhost:8081",
# ]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=_ALLOWED_ORIGINS,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
# endregion / CORS Middleware


# region Middlewares
if config.get(Option.LOG_REQUESTS_ENABLED, "False").lower() == "true":

    class LoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            logger.debug(f"Request {request.method} to {request.url}")
            body = await request.body()
            logger.debug(f"Request body: {body.decode('utf-8') if body else 'None'}")

            response = await call_next(request)

            logger.debug(f"Response status code: {response.status_code}")
            return response

    app.add_middleware(LoggingMiddleware)
# endregion / Middlewares


# region Exception Handlers
async def _exception_handler_for_application_exceptions(_request: Request, exc: Exception):
    """Map `ApplicationError` to `HTTPException`"""
    assert isinstance(exc, ApplicationError)
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


async def _exception_handler_to_enforce_json(_request: Request, exc: Exception):
    """Ensure to return a json response (matching ApiErrorResponseDto) in case of error"""
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value, content={"detail": f"{exc.__class__.__name__}: {exc}"}
    )


app.add_exception_handler(ApplicationError, _exception_handler_for_application_exceptions)
app.add_exception_handler(Exception, _exception_handler_to_enforce_json)
# endregion / Exception Handlers


api_versions_to_load = filter(None, config.get(Option.API_VERSIONS).split(","))
controllers.load(api_versions_to_load)
routers = Controller.routers()
for router in sorted(routers, key=lambda r: r.prefix):
    app.include_router(router)
