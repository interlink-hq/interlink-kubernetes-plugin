import os
from configparser import ConfigParser
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, Final

import pydash as _

_CONFIG_FILE_PATH: Final = "private/config.ini"
_APP_ROOT_PATH: Final = Path(__file__).parent.parent.parent


class Option(Enum):
    """Enum of (section, property_key) options.

    Look up property in `os.environ`, fallback to config file file if missing.
    """

    APP_NAME = ("app", "name")
    APP_DESCRIPTION = ("app", "description")
    APP_VERSION = ("app", "version")
    API_VERSIONS = ("app", "api_versions")
    API_DOCS_PATH = ("app", "api_docs_path")

    LOG_LEVEL = ("log", "level")
    LOG_DIR = ("log", "dir")
    LOG_RICH_ENABLED = ("log", "rich_enabled")
    LOG_REQUESTS_ENABLED = ("log", "requests_enabled")

    K8S_KUBECONFIG_PATH = ("k8s", "kubeconfig_path")
    K8S_KUBERNETES_API_SSL_CA_CERT = ("k8s", "kubernetes_api_ssl_ca_cert")
    K8S_OFFLOADING_NAMESPACE = ("k8s", "offloading_namespace")

    TCP_TUNNEL_BASTION_NAMESPACE = ("tcp_tunnel", "bastion_namespace")
    TCP_TUNNEL_BASTION_CHART_PATH = ("tcp_tunnel", "bastion_chart_path")
    TCP_TUNNEL_GATEWAY_HOST = ("tcp_tunnel", "gateway_host")
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
    _overrides: ClassVar[Dict[str, Dict[str, Any]]] = {}

    @staticmethod
    def __new__(cls):
        """Handle a singleton instance of ConfigParser"""
        if cls._config_parser is None:
            cls._config_parser = ConfigParser()
            cls._config_parser.read(_APP_ROOT_PATH / _CONFIG_FILE_PATH, encoding="utf8")
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
