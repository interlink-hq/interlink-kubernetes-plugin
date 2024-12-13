""" Collection of list utility functions """

from typing import Any, Optional


def omit_none(lizt: list[Any]) -> list[Any]:
    """Remove None elements"""
    return [elem for elem in lizt if elem is not None]


def flatten(lizt: list[Any], exclude_none: Optional[bool] = True) -> list[Any]:
    """Flatten the list to one level deep"""
    result = []
    for elem in lizt:
        if isinstance(elem, list):
            result.extend(elem)
        else:
            result.append(elem)
    return omit_none(result) if exclude_none else result


def intersect(list1: Optional[list[Any]], list2: Optional[list[Any]]) -> list[Any]:
    """Intersect the given lists"""
    if list1 is None or list2 is None:
        return []
    return [item for item in list1 if item in list2]
