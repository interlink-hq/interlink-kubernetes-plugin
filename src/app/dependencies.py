"""
Configure Dependency Injection
"""

import json
import logging
import pathlib
from contextlib import AbstractAsyncContextManager
from typing import Any

from injector import Injector, Module, provider, singleton
from kubernetes import client as k
from kubernetes.client.api import CoreV1Api
from kubernetes.client.configuration import Configuration as KClientConfiguration
from kubernetes.config import kube_config as k_config
from pyhelm3 import Client as HelmClient
from yaml import Dumper, dump

from app.common.config import Config, Option
from app.common.logger_manager import LoggerManager
from app.entities.kubernetes_plugin_configuration import KubernetesPluginConfiguration
from app.services.kubernetes_plugin_service import KubernetesPluginService


# region Configure Injector Module
class InjectorModule(Module):
    """Configure Injector bindings, i.e. how dependencies are provided.

    Note: bindings provide instances when invoking `Injector.get(MyClass)`.
    Bindings are required to provide instances within a given scope (e.g. singleton).
    If no binding is defined for `MyClass` then a fresh new instance is created
    (resolving constructor injected dependencies) and returned.

    See https://github.com/python-injector/injector/blob/master/docs/terminology.rst.
    """

    def configure(self, binder):
        binder.bind(Config, to=Config(), scope=singleton)

    @singleton
    @provider
    def provide_logger(self, config: Config) -> logging.Logger:
        return LoggerManager(config).logger

    @singleton
    @provider
    def provide_kubernetes_plugin_configuration(self, config: Config) -> KubernetesPluginConfiguration:
        kubeconfig_path = pathlib.Path(config.get(Option.K8S_KUBECONFIG_PATH, "private/k8s/kubeconfig.yaml"))
        kubernetes_plugin_configuration = KubernetesPluginConfiguration(kubeconfig_path=str(kubeconfig_path))

        if not kubeconfig_path.exists():
            if not config.get(Option.K8S_KUBECONFIG):
                raise RuntimeError(
                    f"Kubeconfig file at path '{kubeconfig_path}' not found and no kubeconfig provided in config.ini"
                )
            if not kubeconfig_path.parent.exists():
                kubeconfig_path.parent.mkdir(parents=True)
            kubeconfig_dict: dict[str, Any] = json.loads(config.get(Option.K8S_KUBECONFIG))
            with open(kubeconfig_path, "w", encoding="utf-8") as fp:
                dump(kubeconfig_dict, fp, Dumper=Dumper)

        if config.get(Option.K8S_CLIENT_CONFIGURATION):
            config_data: dict[str, Any] = json.loads(config.get(Option.K8S_CLIENT_CONFIGURATION))
            kubernetes_plugin_configuration.client_configuration = KClientConfiguration()
            for key, value in config_data.items():
                setattr(kubernetes_plugin_configuration.client_configuration, key, value)

        return kubernetes_plugin_configuration

    @singleton
    @provider
    def provide_kubernetes_core_api(
        self, config: Config, kubernetes_plugin_configuration: KubernetesPluginConfiguration
    ) -> k.CoreV1Api:

        # In Kubernetes, mutual TLS (mTLS) is used to secure communication between various components:
        # - Client-Server Communication: when a client (e.g., kubectl, kubelet) tries to communicate with the server
        #   (e.g., the k8s API server), both parties authenticate each other using certificates:
        #     - the client presents its client.crt to the server;
        #     - the server verifies this client certificate using its ca.crt;
        #     - similarly, the server presents its server.crt to the client;
        #     - the client verifies the server’s certificate using its ca.crt.
        # - Mutual Trust:
        #     - The CA certificate (ca.crt) is crucial in this process because both the client and server certificates
        #       are signed by a common CA. This ensures that both parties can trust each other based on the CA's
        #       signature.
        #
        # The CA is the issuer/signer of both server (e.g., k8s API server) and client (e.g., kubectl or kubelet) certs.
        #   Set SSL CA cert to prevent the following error:
        #   "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate".
        #   Note: this cert corresponds to clusters[*].cluster.certificate-authority-data in kubeconfig.yaml.
        # configuration.ssl_ca_cert = "private/k8/ca.crt"
        # Alternatively, disable SSL verification, but you'll get the following warning:
        #   "InsecureRequestWarning: Unverified HTTPS request is being made to host '192.84.129.37'"
        #   configuration.verify_ssl = True
        # The client cert is used by clients to authenticate themselves to servers.
        # Set client cert and private key, to prevent 401 errors.
        #   Note: these files correspond to users[*].user.client-certificate/key-data in kubeconfig.yaml.
        # configuration.cert_file = "private/k8s/client.crt"
        # configuration.key_file = "private/k8s/client.key"

        kubeconfig_path = kubernetes_plugin_configuration.kubeconfig_path

        if kubeconfig_path:
            k_config.load_kube_config(
                config_file=kubeconfig_path, client_configuration=kubernetes_plugin_configuration.client_configuration
            )
        else:
            kubeconfig_dict: dict[str, Any] = json.loads(config.get(Option.K8S_KUBECONFIG))
            k_config.load_kube_config_from_dict(
                config_dict=kubeconfig_dict, client_configuration=kubernetes_plugin_configuration.client_configuration
            )

        return CoreV1Api()  # Kubernetes Core client to manage core resources (e.g., pods, services, namespaces)

    @singleton
    @provider
    def provide_helm_client(self, kubernetes_plugin_configuration: KubernetesPluginConfiguration) -> HelmClient:
        return HelmClient(kubeconfig=pathlib.Path(kubernetes_plugin_configuration.kubeconfig_path))

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


def get_lifespan_async_context_managers() -> list[AbstractAsyncContextManager]:
    return []


def preload_dependencies() -> None:
    ...
    # _injector.get(YourTypeName)


# endregion / Public Injector instances
