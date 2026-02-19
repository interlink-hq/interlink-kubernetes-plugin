"""Runtime launcher for the Kubernetes plugin (TCP or Unix socket)."""

from __future__ import annotations

import atexit
import os
from pathlib import Path

import uvicorn

from app.common.config import Config, Option

_VALID_UVICORN_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}


def _parse_log_level(log_level: str) -> str:
    level = log_level.strip().lower()
    if level in _VALID_UVICORN_LOG_LEVELS:
        return level
    return "info"


def _parse_reload_flag(reload: str | None) -> bool:
    if reload is None:
        return False
    return reload.strip().lower() in {"1", "true", "yes", "on"}


def _parse_socket_port(port: str) -> int:
    try:
        return int(port.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid app.socket_port value '{port}': expected integer") from exc


def _extract_host(socket_address: str) -> str:
    host: str = socket_address
    if socket_address.startswith("http://"):
        host = socket_address.removeprefix("http://")
    if socket_address.startswith("https://"):
        host = socket_address.removeprefix("https://")
    return host.strip("/")


def _prepare_unix_socket(socket_address: str) -> str:
    socket_path = socket_address.removeprefix("unix://")

    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Remove stale socket file from previous runs.
    if path.exists():
        if not path.is_socket():
            raise ValueError(f"Refusing to replace non-socket file at '{path}'")
        path.unlink()

    # Gracefully clean up socket file on exit.
    # Note that this won't prevent stale files if the process is killed forcefully (e.g. `kill -9`).
    def _cleanup_socket_file() -> None:
        try:
            if path.exists() and path.is_socket():
                path.unlink()
        except OSError:
            pass

    atexit.register(_cleanup_socket_file)
    return str(path)


def run() -> None:
    config = Config()

    socket_address = str(config.get(Option.SOCKET_ADDRESS))
    socket_port = _parse_socket_port(str(config.get(Option.SOCKET_PORT)))
    log_level = _parse_log_level(str(config.get(Option.LOG_LEVEL, "info")))
    reload_enabled = _parse_reload_flag(os.getenv("UVICORN_RELOAD"))

    # region Unix socket mode
    if socket_address.startswith("unix://"):
        uvicorn.run(
            "main:app",
            uds=_prepare_unix_socket(socket_address),
            log_level=log_level,
            reload=reload_enabled,
        )
        return
    # endregion

    # region TCP socket mode
    host = _extract_host(socket_address)
    if not host:
        raise ValueError("Invalid app.socket_address value: empty host in TCP mode")
    if socket_port <= 0:
        raise ValueError("Invalid app.socket_port value: expected > 0 in TCP mode")

    uvicorn.run("main:app", host=host, port=socket_port, log_level=log_level, reload=reload_enabled)
    # endregion


if __name__ == "__main__":
    run()
