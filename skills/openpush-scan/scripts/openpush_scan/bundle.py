"""The scanner bundled into a skill folder, so an agent can run it with python3 alone.

The bundle is `<skill>/scripts/openpush-scan` (an entry script) plus a copy of this
package without its own `skills/` data. The export script and `install-skill` both
build it from here, so every install carries the same files.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import stat
from typing import List, Optional, Tuple

from . import portable


ENTRY = "openpush-scan"
ENTRY_SOURCE = '''#!/usr/bin/env python3
"""Run the OpenPush Scan CLI bundled with this skill: python3 scripts/openpush-scan <command>."""
import os
import sys

if sys.version_info < (3, 9):
    sys.exit("openpush-scan needs Python 3.9 or later; this is " + sys.version.split()[0] + ".")
sys.dont_write_bytecode = True  # keep the skill folder unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpush_scan.cli import main  # noqa: E402

sys.exit(main())
'''
_SKIP_DIRS = {"__pycache__"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}
_SKIP_NAMES = {".DS_Store"}


SKILL_DATA_PACKAGE = "openpush_scan_skill"


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def skill_dir() -> Optional[Path]:
    """The skill's own files (SKILL.md, agents/, degraded/, reference/), wherever they are.

    In order: an openpush checkout (<repo>/scan/openpush_scan), a wheel built from
    scan/ (package data under openpush_scan/skills), a skill folder this package is
    bundled in (<skill>/scripts/openpush_scan), and a wheel built from the public
    repository, which ships the skill as the data-only package openpush_scan_skill.
    importlib.resources cannot open a package without __init__.py on Python 3.9, so
    that one is located through its import spec.
    """
    here = package_dir()
    candidates = [here.parents[1] / "skills" / "openpush-scan",
                  here / "skills" / "openpush-scan",
                  here.parents[1]]
    try:
        spec = importlib.util.find_spec(SKILL_DATA_PACKAGE)
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.submodule_search_locations:
        candidates += [Path(location) for location in spec.submodule_search_locations]
    return next((path for path in candidates if (path / "SKILL.md").is_file()), None)


def files(package: Path | None = None) -> List[Tuple[str, Path]]:
    """(path under scripts/, source file) for each package file in the bundle."""
    package = package or package_dir()
    found = []
    for path in sorted(package.rglob("*")):
        relative = path.relative_to(package)
        if not path.is_file() or relative.parts[0] == "skills":
            continue
        if _SKIP_DIRS & set(relative.parts) or path.suffix in _SKIP_SUFFIXES or path.name in _SKIP_NAMES:
            continue
        found.append((f"{package.name}/{relative.as_posix()}", path))
    return found


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write(scripts: Path, package: Path | None = None) -> None:
    """Write the bundle into `scripts`, replacing any earlier one."""
    scripts = Path(scripts)
    target = scripts / (package or package_dir()).name
    if target.exists():
        shutil.rmtree(target)
    for relative, source in files(package):
        destination = scripts / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    entry = scripts / ENTRY
    portable.write_text(entry, ENTRY_SOURCE)
    make_executable(entry)
