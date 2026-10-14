from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kiadopt import sexpr
from kiadopt.document import read_document
from kiadopt.env import KicadEnv, resolve_path, third_party_dir
from kiadopt.errors import AdoptError

TABLE_VERSION = 7


@dataclass(frozen=True)
class LibKind:
    table: str
    root: str
    pcm_dir: str
    suffix: str


SYMBOLS = LibKind("sym-lib-table", "sym_lib_table", "symbols", ".kicad_sym")
FOOTPRINTS = LibKind("fp-lib-table", "fp_lib_table", "footprints", ".pretty")


@dataclass(frozen=True)
class LibEntry:
    name: str
    type: str
    uri: str


def read_table(path: Path, env: KicadEnv, project_dir: Path) -> list[LibEntry]:
    return _read_table(path, env, project_dir, frozenset())


def _read_table(
    path: Path, env: KicadEnv, project_dir: Path, seen: frozenset[Path]
) -> list[LibEntry]:
    if path in seen or not path.is_file():
        return []
    entries = []
    for lib in read_document(path).root.children("lib"):
        if lib.child("disabled") is not None:
            continue
        entry = LibEntry(_field(lib, "name"), _field(lib, "type"), _field(lib, "uri"))
        if entry.type == "Table":
            nested = resolve_path(entry.uri, env.variables, project_dir)
            entries += _read_table(nested, env, project_dir, seen | {path})
        else:
            entries.append(entry)
    return entries


def _field(lib: sexpr.Node, name: str) -> str:
    atom = lib.value(name)
    return atom.value if atom is not None else ""


@dataclass(frozen=True)
class Tables:
    kind: LibKind
    project: list[LibEntry]
    global_: list[LibEntry]
    env: KicadEnv
    project_dir: Path

    def find(self, nickname: str) -> Path | None:
        for entry in self.project + self.global_:
            if entry.name == nickname:
                return resolve_path(entry.uri, self.env.variables, self.project_dir)
        return _find_pcm_library(nickname, self.kind, self.env)


def load_tables(kind: LibKind, env: KicadEnv, project_dir: Path) -> Tables:
    project = read_table(project_dir / kind.table, env, project_dir)
    global_ = read_table(env.config_dir / kind.table, env, project_dir)
    return Tables(kind, project, global_, env, project_dir)


def _find_pcm_library(nickname: str, kind: LibKind, env: KicadEnv) -> Path | None:
    # The PCM registers its libraries as PCM_<name>. The table entry may be gone
    # while the package is still installed.
    if not nickname.startswith("PCM_"):
        return None
    name = nickname.removeprefix("PCM_") + kind.suffix
    matches = sorted((third_party_dir(env.variables) / kind.pcm_dir).glob(f"*/{name}"))
    if len(matches) > 1:
        listed = ", ".join(str(match) for match in matches)
        raise AdoptError(f"library {nickname} is ambiguous: {listed}")
    return matches[0] if matches else None


def new_table(kind: LibKind) -> str:
    return f"({kind.root}\n\t(version {TABLE_VERSION})\n)\n"


def add_entry(text: str, nickname: str, uri: str) -> str:
    line = (
        f'\t(lib (name {sexpr.quote(nickname)}) (type "KiCad") (uri {sexpr.quote(uri)})'
        ' (options "") (descr ""))\n'
    )
    return sexpr.append_lines(text, sexpr.parse(text), line)
