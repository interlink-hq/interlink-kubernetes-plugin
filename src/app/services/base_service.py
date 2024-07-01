from abc import ABC
from logging import Logger

from app.common.config import Config


class BaseService(ABC):

    config: Config
    logger: Logger

    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
