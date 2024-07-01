import builtins
import logging
import sys
from typing import Final

import backoff
import rich
from injector import inject
from rich.console import Console
from rich.logging import RichHandler

from app.common.config import Config, Option

CONSOLE_WIDTH: Final = 140


class LoggerManager:

    _config: Config
    _logger: logging.Logger

    @property
    def logger(self) -> logging.Logger:
        assert self._logger is not None
        return self._logger

    @inject
    def __init__(self, config: Config):
        self._config = config
        self._logger = LoggerManager._get_logger(config)

    @staticmethod
    def _get_logger(config: Config) -> logging.Logger:
        log_level = logging.getLevelName(config.get(Option.LOG_LEVEL, "DEBUG"))
        log_rich_enabled = (
            str(config.get(Option.LOG_RICH_ENABLED, "False")).lower() == "true"
        )  # pylint: disable=invalid-name

        if log_rich_enabled:
            builtins.print = rich.print
            # https://rich.readthedocs.io/en/stable/logging.html#logging-handler
            _stdout_handler = RichHandler(console=Console(width=CONSOLE_WIDTH))
        else:
            _stdout_handler = logging.StreamHandler(sys.stdout)

        # Backoff logger - https://github.com/litl/backoff#logging-configuration
        _logger: logging.Logger = logging.getLogger(backoff.__name__)
        _logger.addHandler(_stdout_handler)
        _logger.setLevel(log_level)

        logger: logging.Logger = logging.getLogger(config.get(Option.APP_NAME))
        if logger.hasHandlers():
            logger.handlers.clear()
        logger.addHandler(_stdout_handler)
        logger.setLevel(log_level)
        logger.propagate = False

        # __np_handler = logging.StreamHandler(sys.stdout)
        # np_logger: logging.Logger = logging.getLogger(str(config.get(Option.APP_NAME)) + "(np)")
        # np_logger.addHandler(__np_handler)
        # np_logger.setLevel(log_level)

        return _logger
