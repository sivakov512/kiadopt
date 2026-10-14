from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath

from kiadopt.errors import AdoptError

KICAD_MAJOR = 10
KICAD_VERSION = f"{KICAD_MAJOR}.0"

_VARIABLE = re.compile(r"\$\{(\w+)\}|\$\((\w+)\)")
_VERSIONED = re.compile(r"KICAD\d+_")


@dataclass(frozen=True)
class KicadEnv:
    config_dir: Path
    variables: Mapping[str, str]


def load_env(environ: Mapping[str, str], platform: str = sys.platform) -> KicadEnv:
    config = config_dir(environ, platform)
    # Later sources win, as in KiCad: defaults, kicad_common.json, the environment.
    variables = {**default_variables(environ, platform), **_common_variables(config), **environ}
    return KicadEnv(config, variables)


def config_dir(environ: Mapping[str, str], platform: str) -> Path:
    if base := environ.get("KICAD_CONFIG_HOME"):
        return Path(base) / KICAD_VERSION
    home = _home(environ)
    if platform == "darwin":
        root = home / "Library" / "Preferences" / "kicad"
    elif platform == "win32":
        root = Path(environ.get("APPDATA") or home / "AppData" / "Roaming") / "kicad"
    else:
        root = Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "kicad"
    return root / KICAD_VERSION


def default_variables(environ: Mapping[str, str], platform: str) -> dict[str, str]:
    home = _home(environ)
    documents_3rdparty = home / "Documents" / "KiCad" / KICAD_VERSION / "3rdparty"
    if platform == "darwin":
        shared = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
        third_party = documents_3rdparty
    elif platform == "win32":
        program_files = Path(environ.get("ProgramFiles") or "C:/Program Files")
        shared = program_files / "KiCad" / KICAD_VERSION / "share" / "kicad"
        third_party = documents_3rdparty
    else:
        shared = Path("/usr/share/kicad")
        data = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        third_party = data / "kicad" / KICAD_VERSION / "3rdparty"
    prefix = f"KICAD{KICAD_MAJOR}_"
    return {
        prefix + "3RD_PARTY": str(third_party),
        prefix + "SYMBOL_DIR": str(shared / "symbols"),
        prefix + "FOOTPRINT_DIR": str(shared / "footprints"),
        prefix + "3DMODEL_DIR": str(shared / "3dmodels"),
        prefix + "TEMPLATE_DIR": str(shared / "template"),
    }


def expand(value: str, variables: Mapping[str, str], project_dir: Path) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match[1] or match[2]
        if name == "KIPRJMOD":
            return project_dir.as_posix()
        # Packages made for older KiCad still use ${KICAD8_3RD_PARTY} and alike.
        name = _VERSIONED.sub(f"KICAD{KICAD_MAJOR}_", name, count=1)
        return variables.get(name, match[0])

    return _VARIABLE.sub(substitute, value)


def resolve_path(value: str, variables: Mapping[str, str], project_dir: Path) -> Path:
    path = Path(expand(value, variables, project_dir))
    return path if path.is_absolute() else project_dir / path


def project_reference(path: Path, project_dir: Path) -> str:
    if path.is_relative_to(project_dir):
        return "${KIPRJMOD}/" + path.relative_to(project_dir).as_posix()
    return path.as_posix()


def display_path(path: PurePath, project_dir: Path) -> str:
    if path.is_relative_to(project_dir):
        return path.relative_to(project_dir).as_posix()
    return path.as_posix()


def third_party_dir(variables: Mapping[str, str]) -> Path:
    return Path(variables[f"KICAD{KICAD_MAJOR}_3RD_PARTY"])


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("HOME") or environ.get("USERPROFILE") or Path.home())


def _common_variables(config: Path) -> dict[str, str]:
    path = config / "kicad_common.json"
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_bytes())
    except json.JSONDecodeError as exc:
        raise AdoptError(f"{path}: invalid JSON: {exc}") from exc
    return (settings.get("environment") or {}).get("vars") or {}
