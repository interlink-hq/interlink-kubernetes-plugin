"""
Configure Dependency Injection
"""

import logging
from contextlib import AbstractAsyncContextManager
from typing import List

from injector import Injector, Module, provider, singleton
from kubernetes import client as k
from kubernetes.client.api import CoreV1Api
from kubernetes.client.api_client import ApiClient
from kubernetes.config import kube_config
from pyhelm3 import Client as HelmClient

from app.common.config import Config, Option
from app.common.logger_manager import LoggerManager
from app.services.kubernetes_plugin_service import KubernetesPluginService


# region Configure Injector Module
class InjectorModule(Module):
    """Configure Injector bindings, i.e. how dependencies are provided.

    Note: bindings provide instances when invoking `Injector.get(MyClass)`.
    Bindings are required to provide instances within a given scope (e.g. singleton).
    If no binding is defined for `MyClass` then a fresh new instance is created (resolving constructor
    injected dependencies) and returned.
    """

    def configure(self, binder):
        binder.bind(Config, to=Config(), scope=singleton)

    @singleton
    @provider
    def provide_logger(self, config: Config) -> logging.Logger:
        return LoggerManager(config).logger

    @singleton
    @provider
    def provide_kubernetes_core_api(self, config: Config) -> k.CoreV1Api:
        configuration = k.Configuration()
        # if config.get(Option.K8S_API_SSL_CA_CERT):
        #     configuration.ssl_ca_cert = config.get(Option.K8S_API_SSL_CA_CERT)

        api_client = ApiClient(configuration)
        kube_config.load_kube_config(
            config_file=config.get(Option.K8S_KUBECONFIG_PATH), client_configuration=configuration
        )
        return CoreV1Api(api_client)

    @singleton
    @provider
    def provide_helm_client(self, config: Config) -> HelmClient:
        return HelmClient(kubeconfig=config.get(Option.K8S_KUBECONFIG_PATH))

    @singleton
    @provider
    def provide_kubernetes_plugin_service(
        self, config: Config, logger: logging.Logger, k_api: k.CoreV1Api, h_client: HelmClient
    ) -> KubernetesPluginService:
        return KubernetesPluginService(config, logger, k_api, h_client)


_injector = Injector([InjectorModule()])
# endregion / Configure Injector Module


# region Public Injector instances
def get_config() -> Config:
    return _injector.get(Config)


def get_logger() -> logging.Logger:
    return _injector.get(logging.Logger)


def get_kubernetes_plugin_service() -> KubernetesPluginService:
    return _injector.get(KubernetesPluginService)


def get_lifespan_async_context_managers() -> List[AbstractAsyncContextManager]:
    return []


# endregion / Public Injector instances
