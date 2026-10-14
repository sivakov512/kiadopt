from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kiadopt.plan import Plan


@dataclass(frozen=True)
class ApplyResult:
    backup_dir: Path | None
    written: tuple[Path, ...]


def apply(plan: Plan, now: datetime | None = None) -> ApplyResult:
    """Back up every existing file the plan changes, then write the plan."""
    writes: dict[Path, bytes | Path] = {**plan.copies, **plan.blobs}
    writes.update({path: text.encode("utf-8") for path, text in plan.texts.items()})
    # Everything is written to temporary files first, so a failure on the way
    # (permissions, full disk) leaves the project as it was.
    staged = _stage(writes)
    try:
        backup_dir = _back_up([path for path in writes if path.exists()], plan, now)
    except OSError:
        _discard(staged)
        raise
    for temporary, path in staged:
        temporary.replace(path)
    return ApplyResult(backup_dir, tuple(sorted(writes)))


def _stage(writes: dict[Path, bytes | Path]) -> list[tuple[Path, Path]]:
    staged: list[tuple[Path, Path]] = []
    try:
        for path in sorted(writes):
            content = writes[path]
            data = content if isinstance(content, bytes) else content.read_bytes()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.kiadopt-tmp")
            temporary.write_bytes(data)
            staged.append((temporary, path))
    except OSError:
        _discard(staged)
        raise
    return staged


def _discard(staged: list[tuple[Path, Path]]) -> None:
    for temporary, _ in staged:
        temporary.unlink(missing_ok=True)


def _back_up(paths: list[Path], plan: Plan, now: datetime | None) -> Path | None:
    if not paths:
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup_dir = plan.project.dir / f"{plan.project.name}-backups" / f"adopt-{stamp}"
    for path in sorted(paths):
        copy = backup_dir / _inside_backup(path, plan.project.dir)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)
    return backup_dir


def _inside_backup(path: Path, project_dir: Path) -> Path:
    if path.is_relative_to(project_dir):
        return path.relative_to(project_dir)
    return Path(*path.parts[1:])
