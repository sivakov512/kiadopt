from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kiadopt.env import display_path, resolve_path
from kiadopt.errors import AdoptError
from kiadopt.libtable import Tables


@dataclass(frozen=True)
class Target:
    name: str
    symbol_lib: Path
    footprint_lib: Path
    symbol_registered: bool
    footprint_registered: bool
    models_dir: Path


def matches_prefix(lib_id: str, prefix: str) -> bool:
    nickname = lib_id.partition(":")[0]
    return nickname == prefix or nickname.startswith(prefix + "_")


def resolve_target(
    name: str,
    project_dir: Path,
    symbol_tables: Tables,
    footprint_tables: Tables,
    *,
    prefixes: Sequence[str],
    lib_dir: Path | None,
    models_dir: Path | None,
) -> Target:
    if not name or ":" in name:
        raise AdoptError(f"invalid library name for --to: {name!r}")
    errors = [
        f"--to {name} is one of the --from libraries"
        for prefix in prefixes
        if matches_prefix(name, prefix)
    ]
    lib_dir = (lib_dir or project_dir / "libs").absolute()
    symbol_lib, symbol_registered = _library_path(
        name, symbol_tables, lib_dir / f"{name}.kicad_sym", errors
    )
    footprint_lib, footprint_registered = _library_path(
        name, footprint_tables, lib_dir / f"{name}.pretty", errors
    )
    if symbol_lib.is_dir():
        errors.append(f"{display_path(symbol_lib, project_dir)}: folder libraries not supported")
    if errors:
        raise AdoptError(*errors)
    models_dir = models_dir or footprint_lib.parent / f"{name}.3dshapes"
    return Target(
        name,
        symbol_lib,
        footprint_lib,
        symbol_registered,
        footprint_registered,
        models_dir.absolute(),
    )


def _library_path(name: str, tables: Tables, default: Path, errors: list[str]) -> tuple[Path, bool]:
    """Where the library is or will be, and whether the project table has it already."""
    table = tables.kind.table
    entry = next((entry for entry in tables.project if entry.name == name), None)
    if entry is None:
        if any(entry.name == name for entry in tables.global_):
            errors.append(f"{name} is a global library ({table}), not a project one")
        path, registered = default, False
    else:
        if entry.type != "KiCad":
            errors.append(f"{name} in {table} has type {entry.type}, expected KiCad")
        path, registered = resolve_path(entry.uri, tables.env.variables, tables.project_dir), True
    if not path.is_relative_to(tables.project_dir):
        errors.append(f"library {name} must be inside the project, got {path}")
    return path, registered
