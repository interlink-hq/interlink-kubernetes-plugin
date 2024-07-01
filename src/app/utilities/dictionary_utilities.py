""" Collection of dictionary utility functions """

import dataclasses
from typing import Any, Dict, Iterable, Union


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
