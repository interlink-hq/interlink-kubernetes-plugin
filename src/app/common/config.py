import os
from configparser import ConfigParser
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Final

import pydash as _

# E.g. on devcontainer: /workspaces/interlink-kubernetes-plugin/src
_APP_ROOT_FULL_PATH: Final = Path(__file__).parent.parent.parent


class Option(Enum):
    """Enum of (section, property_key) options.

    Look up property in `os.environ`, fallback to config file file if missing.
    """

    APP_NAME = ("app", "name")
    APP_DESCRIPTION = ("app", "description")
    APP_VERSION = ("app", "version")
    API_VERSIONS = ("app", "api_versions")
    API_DOCS_PATH = ("app", "api_docs_path")
    SOCKET_ADDRESS = ("app", "socket_address")
    SOCKET_PORT = ("app", "socket_port")

    LOG_LEVEL = ("log", "level")
    LOG_DIR = ("log", "dir")
    LOG_RICH_ENABLED = ("log", "rich_enabled")
    LOG_REQUESTS_ENABLED = ("log", "requests_enabled")

    K8S_KUBECONFIG_PATH = ("k8s", "kubeconfig_path")
    K8S_KUBECONFIG = ("k8s", "kubeconfig")
    K8S_CLIENT_CONFIGURATION = ("k8s", "client_configuration")

    OFFLOADING_NAMESPACE_PREFIX = ("offloading", "namespace_prefix")
    OFFLOADING_NAMESPACE_PREFIX_EXCLUSIONS = ("offloading", "namespace_prefix_exclusions")
    OFFLOADING_NODE_SELECTOR = ("offloading", "node_selector")
    OFFLOADING_NODE_TOLERATIONS = ("offloading", "node_tolerations")

    MESH_INIT_CONTAINER = ("mesh", "init_container")
    MESH_STARTUP_PROBE = ("mesh", "startup_probe")

    TCP_TUNNEL_ENABLED = ("tcp_tunnel", "enabled")
    TCP_TUNNEL_BASTION_NAMESPACE = ("tcp_tunnel", "bastion_namespace")
    TCP_TUNNEL_BASTION_CHART_PATH = ("tcp_tunnel", "bastion_chart_path")
    TCP_TUNNEL_GATEWAY_HOST = ("tcp_tunnel", "gateway_host")
    TCP_TUNNEL_GATEWAY_PORT = ("tcp_tunnel", "gateway_port")
    TCP_TUNNEL_GATEWAY_SSH_PRIVATE_KEY = ("tcp_tunnel", "gateway_ssh_private_key")

    def __str__(self) -> str:
        return f"{self.section}.{self.key}"

    def env_var(self) -> str:
        return str(self).upper().replace(".", "_")

    @property
    def section(self) -> str:
        """Get this option's section"""
        return self.value[0]

    @property
    def key(self) -> str:
        """Get this option's key"""
        return self.value[1]


class Config:
    """Centrally manage application configuration properties"""

    _config_parser: ClassVar[ConfigParser | None] = None
    _overrides: ClassVar[dict[str, dict[str, Any]]] = {}

    @staticmethod
    def __new__(cls):
        """Handle a singleton instance of ConfigParser"""
        if cls._config_parser is None:
            config_file_path = os.environ.get("CONFIG_FILE_PATH")
            if not config_file_path:
                config_file_path = "private/config.ini"
            if not config_file_path.startswith("/"):
                config_file_path = str(_APP_ROOT_FULL_PATH / config_file_path)

            cls._config_parser = ConfigParser()
            cls._config_parser.read(config_file_path, encoding="utf8")
        return super(Config, cls).__new__(cls)

    def set(self, option: Option, value: Any) -> None:
        """Set option value"""
        if option.section not in Config._overrides:
            Config._overrides[option.section] = {}
        Config._overrides[option.section][option.key] = value

    def get(self, option: Option, default: Any = None) -> Any:
        """Get option value"""
        # Value set programmatically
        override = _.get(Config._overrides, str(option))
        if override is not None:
            return override
        # Value provided by environment variable
        from_env = _.get(os.environ, option.env_var())
        if from_env is not None:
            return from_env
        # Lookup property in config file
        assert Config._config_parser
        return Config._config_parser.get(option.section, option.key, fallback=default)
