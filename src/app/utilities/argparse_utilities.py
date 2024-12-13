import json
import argparse
from typing import Any, Optional


def check_required_args(
    parser: argparse.ArgumentParser,
    namespace: argparse.Namespace,
    *required_args,
    arg_values: Optional[list[Any]] = None,
) -> None:
    """Check required arguments

    Args:
        parser (argparse.ArgumentParser): The parser object.
        namespace (argparse.Namespace): The namespace object containing parsed arguments.
        arg_values (Optional[list[Any]], optional): Expected values for required args. Defaults to None.
    """
    missing_args = list()
    if arg_values is None:
        arg_values = [None] * len(required_args)
    for arg_name, arg_val in zip(required_args, arg_values):
        if arg_name not in namespace:
            missing_args.append(arg_name)
        elif arg_val is not None and getattr(namespace, arg_name) != arg_val:
            parser.error(f"Required arg '{arg_name}' expected value: {arg_val}")
    if missing_args:
        parser.error(f"Missing required args: {missing_args}")


def parse_encoded_parameters(parameters: dict[str, Any] | None, key: str) -> dict[str, Any]:
    """Parse ecoded parameters.
    Return empty object `{}` if no parameters with the given key were found."""
    if parameters and parameters.get(key):
        encoded_parameters = parameters.get(key)
        if isinstance(encoded_parameters, str):
            return json.loads(encoded_parameters)
    return {}
