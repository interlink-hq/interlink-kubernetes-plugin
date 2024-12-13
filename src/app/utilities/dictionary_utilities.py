""" Collection of dictionary utility functions """

import dataclasses
import typing as t
from datetime import datetime
from typing import Any, Dict, Iterable, Union

import pydash as _

T = t.TypeVar("T")
T2 = t.TypeVar("T2")  # pylint: disable=invalid-name
T3 = t.TypeVar("T3")  # pylint: disable=invalid-name
T4 = t.TypeVar("T4")  # pylint: disable=invalid-name
T5 = t.TypeVar("T5")  # pylint: disable=invalid-name


def pop_fields(dikt: Dict, field_list: Iterable[str]) -> Dict:
    """Pop a list of fields from the dictionary object"""
    for field in field_list:
        dikt.pop(field)
    return dikt


def keep_fields(dikt: Dict, field_list: Union[Iterable[str], Any]) -> Dict:
    """Keep the given list of fields, pop the others"""
    if isinstance(field_list, Iterable):
        fields = field_list
    elif dataclasses.is_dataclass(field_list):
        fields = [field.name for field in dataclasses.fields(field_list)]
    else:
        raise RuntimeError("Exptected either an iterable or dataclass type")

    for key in list(dikt):
        if key not in fields:
            dikt.pop(key)
    return dikt


def map_keys_deep(dikt: t.Mapping[T, T2], iteratee: t.Callable[[T2, T, t.dict[T, T2]], T3]) -> t.dict[T3, T2]:
    def recursive_map_keys(value):
        if _.is_dict(value):
            # Apply map_keys at the current level
            mapped_value = _.map_keys(value, iteratee)
            # Recursively apply to nested dictionaries
            return {k: recursive_map_keys(v) for k, v in mapped_value.items()}
        elif isinstance(value, list):
            # Recursively apply to elements in a list
            return [recursive_map_keys(item) for item in value]
        else:
            # Return the value as is if it's not a dictionary or list
            return value

    return recursive_map_keys(dikt)  # type: ignore


def map_key_names(dikt: t.Mapping[str, T], key_map: dict[str, str], deep=False, reverse=False) -> t.Mapping[str, T]:
    if reverse:
        key_map = {v: k for k, v in key_map.items()}
    if deep:
        return map_keys_deep(dikt, lambda _val, key, _obj: key_map.get(key, key))
    return {key_map[k]: v for k, v in dikt.items() if k in key_map}


def map_datetime_to_str(dikt: t.Mapping[T, Any], datetime_format="%Y-%m-%dT%H:%M:%SZ") -> t.Mapping[T, Any]:
    return _.map_values_deep(dikt, lambda val: val.strftime(datetime_format) if isinstance(val, datetime) else val)
