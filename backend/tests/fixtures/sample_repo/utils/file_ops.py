"""File operation utilities.

Intentional bugs:
  - get_first_item: IndexError when list is empty
  - read_report: unclosed file handle (ResourceWarning)
  - compute_ratio: ZeroDivisionError when denominator is zero
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class FileOpsError(Exception):
    """Raised for filesystem-related errors."""


def get_first_item(items: list[Any]) -> Any:
    """Return the first element of *items*.

    BUG: IndexError when *items* is an empty list.
    Should check ``if not items`` before indexing.
    """
    return items[0]                         # BUG: IndexError if items is empty


def read_report(report_path: str) -> str:
    """Read a report file and return its contents as a string.

    BUG: File handle is never closed — ResourceWarning / file-descriptor leak.
    Should use ``with open(...) as f:`` or ``f.close()`` in a finally block.
    """
    f = open(report_path, encoding="utf-8")     # BUG: unclosed file handle
    return f.read()


def compute_ratio(numerator: float, denominator: float) -> float:
    """Return *numerator* / *denominator*.

    BUG: ZeroDivisionError when *denominator* is 0.
    No guard for division-by-zero.
    """
    return numerator / denominator          # BUG: ZeroDivisionError if denominator == 0


def list_data_files(directory: str, extension: str = ".csv") -> list[str]:
    """Return all files with *extension* in *directory*.

    Raises ``FileOpsError`` if *directory* does not exist.
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        raise FileOpsError(f"Directory not found: {directory}")
    return [
        str(p) for p in dir_path.iterdir()
        if p.is_file() and p.suffix == extension
    ]


def safe_read(file_path: str, base_dir: str) -> str:
    """Read *file_path* only if it resolves within *base_dir*.

    This is the CORRECT implementation for comparison with the buggy versions.
    """
    base = Path(base_dir).resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise FileOpsError(f"Path traversal detected: {file_path!r}")
    return target.read_text(encoding="utf-8")
