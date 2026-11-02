"""Replace a skill folder in one step, so agents never see a half-written or second copy.

The new copy is written to a hidden staging folder outside every skills folder:
beside the skills folder's parent, so `.agents/skills/openpush-scan` stages in
`<project>/.openpush-scan-staging-<random>`. That is the same filesystem, so each
rename is atomic. The old folder is renamed to a hidden backup, the staging folder
is renamed into place, and the backup is deleted. If any step fails or is
interrupted, the old folder is put back and the staging folder removed.
"""

from __future__ import annotations

from pathlib import Path
import secrets
import shutil
from typing import Callable, Iterable, List, Tuple, Union

from . import install_record as record
from . import portable


STAGING_PREFIX = ".openpush-scan-staging-"
BACKUP_PREFIX = ".openpush-scan-backup-"

Content = Union[Path, Callable[[], str]]


def work_area(root: Path) -> Path:
    """Beside the skills folder's parent: <base> for <base>/.agents/skills/openpush-scan."""
    return root.parent.parent.parent


def replace(root: Path, files: Iterable[Tuple[Path, Content]],
            finish: Callable[[Path], None]) -> bool:
    """Write `files` (and whatever `finish` adds) as `root`. Returns whether a folder was replaced."""
    area = work_area(root)
    token = secrets.token_hex(6)
    staging = area / f"{STAGING_PREFIX}{token}"
    backup = area / f"{BACKUP_PREFIX}{token}"
    had_old = _present(root)
    placed = False
    try:
        staging.mkdir()
        for relative, content in files:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, Path):
                shutil.copy2(content, destination)
            else:
                portable.write_text(destination, content())
        finish(staging)
        root.parent.mkdir(parents=True, exist_ok=True)
        if had_old:
            portable.rename(root, backup)
        portable.rename(staging, root)
        placed = True
    finally:
        if not placed:
            # Put the old folder back, whichever step failed or was interrupted.
            if _present(backup) and not _present(root):
                portable.rename(backup, root)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    if _present(backup):
        try:
            record.remove_folder(backup)
        except OSError:
            pass  # hidden and outside the skills folders; the next run removes it
    return had_old


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink() or portable.is_link(path)


def clean_leftovers(areas: Iterable[Path]) -> List[Path]:
    """Remove staging and backup folders an interrupted run left behind.

    Only folders with our exact prefixes that hold our record or a SKILL.md named
    openpush-scan are removed.
    """
    removed = []
    for area in dict.fromkeys(areas):
        try:
            entries = list(area.iterdir())
        except OSError:
            continue
        for entry in sorted(entries):
            if not entry.name.startswith((STAGING_PREFIX, BACKUP_PREFIX)):
                continue
            if not (entry.is_dir() and record.is_ours(entry)):
                continue
            try:
                record.remove_folder(entry)
            except OSError:
                continue
            removed.append(entry)
    return removed
