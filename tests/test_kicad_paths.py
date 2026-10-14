from pathlib import Path

import pytest

from kiadopt.env import (
    config_dir,
    default_variables,
    expand,
    load_env,
    resolve_path,
)
from kiadopt.errors import AdoptError
from tests.helpers import MINI

PROJECT = Path("/work/demo")


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("darwin", {"HOME": "/Users/me"}, "/Users/me/Library/Preferences/kicad/10.0"),
        ("linux", {"HOME": "/home/me"}, "/home/me/.config/kicad/10.0"),
        ("linux", {"HOME": "/home/me", "XDG_CONFIG_HOME": "/xdg"}, "/xdg/kicad/10.0"),
        ("win32", {"USERPROFILE": "C:/Users/me", "APPDATA": "C:/AppData"}, "C:/AppData/kicad/10.0"),
        ("darwin", {"HOME": "/Users/me", "KICAD_CONFIG_HOME": "/cfg"}, "/cfg/10.0"),
    ],
    ids=["macos", "linux", "linux-xdg", "windows", "kicad-config-home"],
)
def test_finds_config_dir(platform: str, environ: dict[str, str], expected: str) -> None:
    assert config_dir(environ, platform) == Path(expected)


@pytest.mark.parametrize(
    ("platform", "environ", "third_party", "symbols"),
    [
        (
            "darwin",
            {"HOME": "/Users/me"},
            "/Users/me/Documents/KiCad/10.0/3rdparty",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
        ),
        (
            "linux",
            {"HOME": "/home/me"},
            "/home/me/.local/share/kicad/10.0/3rdparty",
            "/usr/share/kicad/symbols",
        ),
        (
            "linux",
            {"HOME": "/home/me", "XDG_DATA_HOME": "/data"},
            "/data/kicad/10.0/3rdparty",
            "/usr/share/kicad/symbols",
        ),
        (
            "win32",
            {"USERPROFILE": "C:/Users/me", "ProgramFiles": "D:/Programs"},
            "C:/Users/me/Documents/KiCad/10.0/3rdparty",
            "D:/Programs/KiCad/10.0/share/kicad/symbols",
        ),
    ],
    ids=["macos", "linux", "linux-xdg", "windows"],
)
def test_defaults_to_standard_install_paths(
    platform: str, environ: dict[str, str], third_party: str, symbols: str
) -> None:
    variables = default_variables(environ, platform)

    assert Path(variables["KICAD10_3RD_PARTY"]) == Path(third_party)
    assert Path(variables["KICAD10_SYMBOL_DIR"]) == Path(symbols)


def test_kicad_common_overrides_defaults() -> None:
    env = load_env({"HOME": "/home/me", "KICAD_CONFIG_HOME": str(MINI / "config")}, "linux")

    assert env.config_dir == MINI / "config/10.0"
    assert env.variables["KICAD10_3RD_PARTY"] == "/from/kicad_common/3rdparty"
    assert env.variables["MINI_DOCS"] == "/opt/mini/docs"
    assert env.variables["KICAD10_SYMBOL_DIR"] == "/usr/share/kicad/symbols"


def test_environment_overrides_kicad_common() -> None:
    environ = {"HOME": "/h", "KICAD_CONFIG_HOME": str(MINI / "config"), "KICAD10_3RD_PARTY": "/env"}

    assert load_env(environ, "linux").variables["KICAD10_3RD_PARTY"] == "/env"


def test_works_without_kicad_common(tmp_path: Path) -> None:
    env = load_env({"HOME": str(tmp_path), "KICAD_CONFIG_HOME": str(tmp_path)}, "linux")

    assert "MINI_DOCS" not in env.variables


def test_raises_on_broken_kicad_common(tmp_path: Path) -> None:
    (tmp_path / "10.0").mkdir()
    (tmp_path / "10.0/kicad_common.json").write_text("{broken")

    with pytest.raises(AdoptError, match="invalid JSON"):
        load_env({"HOME": str(tmp_path), "KICAD_CONFIG_HOME": str(tmp_path)}, "linux")


def test_expands_both_variable_syntaxes_and_project_dir() -> None:
    variables = {"KICAD10_3RD_PARTY": "/3rd", "LIBS": "/libs"}

    assert expand("${KICAD10_3RD_PARTY}/a", variables, PROJECT) == "/3rd/a"
    assert expand("$(LIBS)/b", variables, PROJECT) == "/libs/b"
    assert expand("${KIPRJMOD}/libs", variables, PROJECT) == "/work/demo/libs"


def test_leaves_unknown_variable_as_is() -> None:
    assert expand("${UNKNOWN}/x", {}, PROJECT) == "${UNKNOWN}/x"


@pytest.mark.parametrize("old", ["KICAD6_3RD_PARTY", "KICAD8_3RD_PARTY", "KICAD9_3RD_PARTY"])
def test_maps_variables_of_older_kicad_to_kicad_10(old: str) -> None:
    variables = {"KICAD10_3RD_PARTY": "/3rd", "KICAD10_3DMODEL_DIR": "/models"}

    assert expand(f"${{{old}}}/pkg", variables, PROJECT) == "/3rd/pkg"
    assert expand("${KICAD9_3DMODEL_DIR}/R.step", variables, PROJECT) == "/models/R.step"


def test_resolves_relative_path_from_project() -> None:
    assert resolve_path("parts/x.step", {}, PROJECT) == PROJECT / "parts/x.step"
    assert resolve_path("/abs/x.step", {}, PROJECT) == Path("/abs/x.step")
