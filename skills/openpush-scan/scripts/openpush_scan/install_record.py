"""Who owns a skill folder, and the record `install-skill` keeps for it.

The record, `.openpush-scan-install.json`:

    {"name": "openpush-scan", "version": "0.1.0",
     "targets": {"codex": [".codex/agents/openpush_scanner.toml", ...], "amp": []}}

`version` is null when the folder's files came from elsewhere. Each target lists
the agent files written for it, relative to the project or home directory the
install used. Only listed files are ever deleted.

The record normally lives inside the skill folder. A folder that `npx skills`
manages is that tool's state, so its record is kept beside the skills folder
instead (`.agents/.openpush-scan-install.json` for `.agents/skills/openpush-scan`)
and nothing inside the folder or in the npx lock files is changed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import portable


MARKER = ".openpush-scan-install.json"
SKILL_NAME = "openpush-scan"

ABSENT, RECORDED, SKILL_ONLY, NPX, FOREIGN = "absent", "recorded", "skill-only", "npx", "foreign"


def read(path: Path) -> Optional[Dict[str, Any]]:
    """The record at `path`, a record file or a skill folder holding one."""
    path = path / MARKER if path.is_dir() else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("name") != SKILL_NAME:
        return None
    targets = data.get("targets")
    data["targets"] = {str(name): [str(item) for item in paths if isinstance(item, str)]
                       for name, paths in (targets.items() if isinstance(targets, dict) else [])
                       if isinstance(paths, list)}
    return data


def write(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    portable.write_text(path, json.dumps(record, indent=2, sort_keys=True) + "\n")


def new(version: Optional[str]) -> Dict[str, Any]:
    return {"name": SKILL_NAME, "version": version, "targets": {}}


def sidecar(root: Path) -> Path:
    """Where the record for an npx-managed folder lives: beside its skills folder."""
    return root.parent.parent / MARKER


def record_path(root: Path, state: str) -> Path:
    return sidecar(root) if state == NPX else root / MARKER


def load(root: Path, state: str) -> Dict[str, Any]:
    """The current record for a folder in `state`, or an empty one."""
    if state == NPX:
        return read(sidecar(root)) or read(root) or new(None)
    return read(root) or new(None)


def npx_lock(base: Path, user: bool, environ=None) -> Path:
    """The lock file `npx skills` (1.7) keeps for this scope.

    Project installs: <project>/skills-lock.json. Global installs (-g):
    $XDG_STATE_HOME/skills/.skill-lock.json, else ~/.agents/.skill-lock.json, where
    ~ is the home directory on every platform (%USERPROFILE% on Windows).
    """
    if not user:
        return base / "skills-lock.json"
    state_home = (os.environ if environ is None else environ).get("XDG_STATE_HOME")
    if state_home:
        return type(base)(state_home) / "skills" / ".skill-lock.json"
    return base / ".agents" / ".skill-lock.json"


def npx_lists_skill(base: Path, user: bool) -> bool:
    try:
        data = json.loads(npx_lock(base, user).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    skills = data.get("skills") if isinstance(data, dict) else None
    return isinstance(skills, dict) and SKILL_NAME in skills


def ownership(root: Path, base: Path, user: bool) -> str:
    """absent, recorded, skill-only, npx or foreign.

    recorded: our record is inside and names a version, so install-skill wrote the
    files. npx: the npx lock for this scope lists openpush-scan and the folder's
    SKILL.md is ours. skill-only: SKILL.md is ours, nothing else is known.
    """
    if not root.exists() and not root.is_symlink():
        return ABSENT
    inside = read(root)
    if inside is not None and inside.get("version"):
        return RECORDED
    ours = inside is not None or skill_name(root / "SKILL.md") == SKILL_NAME
    if not ours:
        return FOREIGN
    if npx_lists_skill(base, user):
        return NPX
    return RECORDED if inside is not None else SKILL_ONLY


def skill_name(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return None
    for line in text[4:].split("\n---\n", 1)[0].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "name":
            return value.strip().strip("\"'")
    return None


def is_ours(folder: Path) -> bool:
    """A folder holding our record or a SKILL.md named openpush-scan."""
    return read(folder) is not None or skill_name(folder / "SKILL.md") == SKILL_NAME


def remove_folder(root: Path) -> None:
    """Remove a skill folder, or only the link when it is a link or Windows junction."""
    portable.remove_tree(root)


def relative(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def listed(record: Dict[str, Any], target: str) -> List[str]:
    return list(record.get("targets", {}).get(target, []))
