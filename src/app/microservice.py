"""
FastAPI entry point: load controllers and start the app.
"""

from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi_router_controller import Controller

from app.common.config import Option
from app.utilities.async_utilities import manage_contexts

from . import controllers
from .dependencies import get_config, get_lifespan_async_context_managers
from .services.exceptions import DataNotFoundError, ServiceError

config = get_config()

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
            "name": "Research DB Analysis Tool API",
            "description": "API for accessing Research DB Analysis Tool functionalities",
        }
    ],
)


# region CORS
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
# endregion / CORS


# region Exception Handlers
async def _exception_handler_for_service_exceptions(_request: Request, exc: Exception):
    """Set status code for selected errors"""
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
    if isinstance(exc, DataNotFoundError):
        status_code = HTTPStatus.NOT_FOUND.value
    raise HTTPException(status_code=status_code, detail=str(exc))


async def _exception_handler_to_enforce_json(_request: Request, exc: Exception):
    """Ensure to return a json response (matching ApiErrorResponseDto) in case of error"""
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value, content={"detail": str(exc)})


app.add_exception_handler(ServiceError, _exception_handler_for_service_exceptions)
app.add_exception_handler(Exception, _exception_handler_to_enforce_json)
# endregion / Exception Handlers


api_versions_to_load = filter(None, config.get(Option.API_VERSIONS).split(","))
controllers.load(api_versions_to_load)
routers = Controller.routers()
for router in sorted(routers, key=lambda r: r.prefix):
    app.include_router(router)
