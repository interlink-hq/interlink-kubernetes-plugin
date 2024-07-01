from os.path import dirname, join
from typing import Iterator

from fastapi_router_controller import ControllerLoader


def load(api_versions: Iterator[str]):
    """
    Load controllers for each api version package.

    :param `api_versions`: list of versions, e.g. ["v1","v1.1","v2"]
    """
    for api_version in api_versions:
        return ControllerLoader.load(join(dirname(__file__), api_version), f"{__package__}.{api_version}")
        # Use the following to publish all versions (modules are searched recursively):
        # return ControllerLoader.load(dirname(__file__), __package__)
