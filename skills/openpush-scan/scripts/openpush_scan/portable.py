"""Small helpers that keep the scanner and installer working the same on Windows.

- Text files are written as UTF-8 with LF line endings on every platform.
- Console output never crashes on a code page that lacks a character (cp1252 has
  no `→`); such characters print as `?`.
- Folder links include Windows junctions, which `npx skills` creates there, and
  a link is removed without touching its target.
- Trees with read-only files can be removed (common on Windows).
- The Python interpreter for the bundled scanner is chosen in the order SKILL.md
  gives: python3, then the Windows launcher `py -3`, then python.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence, Tuple


PYTHON_CANDIDATES: Tuple[Tuple[str, ...], ...] = (("python3",), ("py", "-3"), ("python",))
MINIMUM_PYTHON = (3, 9)
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: symlinks and junctions


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def safe_console(*streams) -> None:
    """Print `?` for characters the console encoding lacks, instead of failing."""
    for stream in streams or (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "ascii"
        try:
            "→…·—•".encode(encoding)
        except (LookupError, UnicodeEncodeError):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="replace")


def is_link(path: Path) -> bool:
    """A symbolic link, or on Windows a directory junction."""
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return False


def remove_tree(path: Path) -> None:
    """Remove a folder, or only the link when it is a link or junction."""
    if is_link(path):
        try:
            os.unlink(path)
        except OSError:
            os.rmdir(path)  # Windows removes directory links and junctions with rmdir
        return
    top = os.path.abspath(path)

    def clear_read_only(function: Callable, failed: str, _error) -> None:
        """Make the path (Windows read-only attribute) and, inside the tree, its folder
        (POSIX) writable, then retry."""
        parent = os.path.dirname(os.path.abspath(failed))
        inside = parent == top or parent.startswith(top + os.sep)
        for item in ((parent, failed) if inside else (failed,)):
            try:
                os.chmod(item, os.stat(item).st_mode | stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            except OSError:
                pass
        function(failed)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_read_only)
    else:
        shutil.rmtree(path, onerror=clear_read_only)


def rename(source: Path, target: Path, *, attempts: int = 5, delay: float = 0.2) -> None:
    """os.rename onto a target that does not exist. On Windows, retry briefly while
    another process (an editor, an agent, antivirus) holds a file open."""
    for attempt in range(attempts if os.name == "nt" else 1):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1 or os.name != "nt":
                raise
            time.sleep(delay)


def python_version(command: Sequence[str]) -> Optional[Tuple[int, int]]:
    """(major, minor) printed by `<command> --version`, or None when it prints none.

    The Microsoft Store `python3` stub prints nothing useful, so it reads as missing.
    """
    try:
        result = subprocess.run([*command, "--version"], capture_output=True, text=True, errors="replace",
                                timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    match = re.search(r"Python (\d+)\.(\d+)", (result.stdout or "") + (result.stderr or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def choose_python(version_of: Optional[Callable[[Sequence[str]], Optional[Tuple[int, int]]]] = None
                  ) -> Optional[Tuple[str, ...]]:
    """The first of python3, py -3 and python that reports Python 3.9 or later."""
    version_of = version_of or python_version
    for command in PYTHON_CANDIDATES:
        version = version_of(command)
        if version is not None and version >= MINIMUM_PYTHON:
            return command
    return None
