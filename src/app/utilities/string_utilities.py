""" Collection of string utility functions """

import re
from typing import Any, Dict, Final, List, Optional, Tuple, Union

import typo
from bs4 import BeautifulSoup
from cleantext import clean
from semver import Version


def to_camel_case(snake_or_kebab: str) -> str:
    """Convert a string from kebab ('-' separator) or snake case ('_' separator) to camel case"""
    return snake_or_kebab.title().replace(" ", "").replace("-", "").replace("_", "")


def typo_generator(strings: Union[str, List[str], Dict[str, str]], nr_loops: int = 10, nr_errors: int = 2):
    """
    See also: https://github.com/BigDaMa/error-generator, https://github.com/ail-project/ail-typo-squatting
    """
    mangler_fns = [
        "char_swap",
        "extra_char",
        "missing_char",
        "nearby_char",
        "random_space",
        "repeated_char",
        "similar_char",
        "skipped_space",
        "unichar",
    ]
    for _ in range(0, nr_loops):
        fns_index = sorted(range(0, len(mangler_fns)))
        for fn_index in fns_index:
            if isinstance(strings, str):
                mangled_str = typo.StrErrer(strings)
                for _ in range(0, nr_errors):
                    yield (getattr(mangled_str, mangler_fns[fn_index])()).result
            elif isinstance(strings, list):
                mangled_list = [typo.StrErrer(string) for string in strings]
                for _ in range(0, nr_errors):
                    yield [(getattr(mangled, mangler_fns[fn_index])()).result for mangled in mangled_list]
            elif isinstance(strings, dict):
                mangled_dict = {key: typo.StrErrer(string) for key, string in strings.items()}
                for _ in range(0, nr_errors):
                    yield {
                        key: (getattr(mangled, mangler_fns[fn_index])()).result for key, mangled in mangled_dict.items()
                    }


def clean_text(text: str, **kwargs) -> str:
    """Apply supported tools to clean the input text.
    Supported tools: `bs4_parser`, `cleantext`.
    Note: if the cleaned text is a whitespace string, the empty string is returned
    """
    if not isinstance(text, str):
        return text
    if "bs4_parser" in kwargs:
        text = BeautifulSoup(text, **kwargs["bs4_parser"]).text
    if "clean_text" in kwargs:
        text = clean(text, **kwargs["clean_text"])
    text = text.replace(".\n", ". ").replace("\n", " ").replace("\t", " ")
    if text.isspace():
        return ""
    return text


def truncate_string(dikt: Dict[str, Any], size: int = 100, inplace=False) -> Dict[str, Any]:
    """Truncate all string values in the given `dikt` object"""

    def truncate_or_noop(val: Any) -> Any:
        return val[:size] if isinstance(val, str) else val

    if inplace:
        for key, val in dikt.items():
            dikt[key] = truncate_or_noop(val)
        return dikt
    else:
        return {key: truncate_or_noop(val) for key, val in dikt.items()}


SEM_VER_RE: Final = re.compile(
    r"""[vV]?
        (?P<major>0|[1-9]\d*)
        (\.
            (?P<minor>0|[1-9]\d*)
            (\.
                (?P<patch>0|[1-9]\d*)
            )?
        )?
        $
    """,
    re.VERBOSE,
)


def parse_semver(version: str) -> Tuple[Optional[str], Optional[Version]]:
    """
    Converts a (possibly incomplete) version string into a semver-compatible Version object.

    * Tries to parse a version string (``major.minor.patch``).
    * If not enough components can be found, missing components are
        set to zero to obtain a valid semver version.

    :param str version: the version string to convert
    :return: a tuple with the matching version string and a :class:`Version` instance
    :rtype: tuple(str | None, :class:`Version` | None)
    """
    match = SEM_VER_RE.search(version)
    if not match:
        return None, None
    ver = {key: 0 if value is None else value for key, value in match.groupdict().items()}
    ver = Version(**ver)  # type: ignore
    return match.group(0), ver
