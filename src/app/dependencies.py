"""FastAPI dependency functions"""

import logging
from contextlib import AbstractAsyncContextManager
from typing import List

from injector import Injector, Module, provider, singleton

from app.common.config import Config
from app.common.logger_manager import LoggerManager
from app.services.kubernetes_plugin_service import KubernetesPluginService


# region Configure Injector Module
class InjectorModule(Module):
    """Register Injector singletons.

    Note: `Injector.get(MyClass)` gets the instance from the corresponding `@provider` if defined,
    honoring the @singleton annotation, otherwise a fresh new instance of `MyClass` is created
    (resolving constructor injected dependencies) and returned.
    """

    @singleton
    @provider
    def provide_config(self) -> Config:
        return Config()

    @singleton
    @provider
    def provide_logger(self, config: Config) -> logging.Logger:
        return LoggerManager(config).logger

    @singleton
    @provider
    def provide_kubernetes_plugin_service(self, config: Config, logger: logging.Logger) -> KubernetesPluginService:
        return KubernetesPluginService(config, logger)


_injector = Injector([InjectorModule()])
# endregion / Configure Injector Module


# region Export Injector instances
def get_config() -> Config:
    return _injector.get(Config)


def get_kubernetes_plugin_service() -> KubernetesPluginService:
    return _injector.get(KubernetesPluginService)


def get_lifespan_async_context_managers() -> List[AbstractAsyncContextManager]:
    return []


# endregion / Export Injector instances
