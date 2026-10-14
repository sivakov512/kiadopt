from __future__ import annotations

import shutil
from pathlib import Path

from kiadopt import Action, KicadEnv, Plan
from kiadopt.symbols import read_symbol_lib

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_KICAD = FIXTURES / "kicad"
MINI = FIXTURES / "mini"
PDF = b"%PDF-1.4\n"

ACME = "com_github_acme_kicad-library"
ACME_SYMBOLS = DEMO_KICAD / "3rdparty/symbols" / ACME
ACME_FOOTPRINTS = DEMO_KICAD / "3rdparty/footprints" / ACME


def stock_environ(kicad: Path, home: Path) -> dict[str, str]:
    stock = kicad / "stock"
    return {
        "HOME": str(home),
        "KICAD_CONFIG_HOME": str(kicad / "config"),
        "KICAD10_3RD_PARTY": str(kicad / "3rdparty"),
        "KICAD10_SYMBOL_DIR": str(stock / "symbols"),
        "KICAD10_FOOTPRINT_DIR": str(stock / "footprints"),
        "KICAD10_3DMODEL_DIR": str(stock / "3dmodels"),
        "KICAD10_TEMPLATE_DIR": str(stock / "template"),
    }


class FakeWeb:
    def __init__(self, pages: dict[str, bytes] | None = None) -> None:
        self.pages = pages or {}
        self.requests: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        if url not in self.pages:
            raise OSError(f"cannot reach {url}")
        return self.pages[url]


def actions(result: Plan, kind: str) -> list[Action]:
    return [action for action in result.actions if action.kind == kind]


def subjects(result: Plan, kind: str) -> list[str]:
    return [action.subject for action in actions(result, kind)]


def targets(result: Plan, kind: str) -> list[str]:
    return [action.target for action in actions(result, kind)]


def read(path: Path) -> str:
    return path.read_bytes().decode()


def library_symbols(project: Path, name: str = "Local") -> dict[str, str]:
    return read_symbol_lib(project / "libs" / f"{name}.kicad_sym").blocks


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def register_library(project: Path, table: str, name: str, uri: str) -> None:
    path = project / table
    text = read(path)
    line = f'\t(lib (name "{name}") (type "KiCad") (uri "{uri}") (options "") (descr ""))\n'
    path.write_text(text[: text.rindex(")")] + line + ")\n")


def with_variable(env: KicadEnv, name: str, value: str) -> KicadEnv:
    return KicadEnv(env.config_dir, {**env.variables, name: value})


def editable_third_party(project: Path, env: KicadEnv) -> tuple[Path, KicadEnv]:
    """A copy of the PCM folder that a test may change, and an env pointing at it."""
    third = project.parent / "3rdparty"
    shutil.copytree(env.variables["KICAD10_3RD_PARTY"], third)
    return third, with_variable(env, "KICAD10_3RD_PARTY", str(third))
