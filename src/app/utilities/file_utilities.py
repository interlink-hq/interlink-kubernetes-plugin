from pathlib import Path
from typing import Optional


def get_file_path_variant(file_path: str, variant: Optional[str] = None, separator: Optional[str] = "_") -> str:
    """Modify `file_path` by injecting `separator` followed by `variant` (if defined) before path suffix"""
    if not variant:
        return file_path
    ext = get_file_extension(file_path, True)
    path_no_ext = file_path if not ext else file_path[: -len(ext)]
    return f"{path_no_ext}{separator if separator else ''}{variant}{ext}"


def get_file_extension(file_path: str, with_leading_perdiod: bool = False) -> str:
    """The final component's suffixes, if any, with/without the leading period. For example: 'tar.gz'"""
    path = Path(file_path)
    ext = "".join(path.suffixes)
    return ext[1:] if ext.startswith(".") and not with_leading_perdiod else ext
