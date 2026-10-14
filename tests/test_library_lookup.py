import shutil
from pathlib import Path

import pytest

from kiadopt import KicadEnv
from kiadopt.errors import AdoptError
from kiadopt.libtable import FOOTPRINTS, SYMBOLS, load_tables, read_table
from tests.helpers import MINI, register_library, with_variable


def test_expands_nested_tables_and_skips_disabled_entries(mini: Path, mini_env: KicadEnv) -> None:
    entries = read_table(MINI / "config/10.0/sym-lib-table", mini_env, mini)

    assert [entry.name for entry in entries] == ["Device", "PCM_Mini_Parts", "Shadowed"]
    assert entries[0].uri == "${KICAD10_SYMBOL_DIR}/Device.kicad_sym"


def test_stops_at_nested_table_loop(tmp_path: Path, mini_env: KicadEnv) -> None:
    table = tmp_path / "sym-lib-table"
    table.write_text(f'(sym_lib_table (lib (name "Self") (type "Table") (uri "{table}")))')

    assert read_table(table, mini_env, tmp_path) == []


def test_finds_library_in_global_table(mini: Path, mini_env: KicadEnv) -> None:
    found = load_tables(SYMBOLS, mini_env, mini).find("Device")

    assert found == MINI / "stock/symbols/Device.kicad_sym"


def test_prefers_project_table_over_global(mini: Path, mini_env: KicadEnv) -> None:
    (mini / "sym-lib-table").write_text("(sym_lib_table\n\t(version 7)\n)\n")
    register_library(mini, "sym-lib-table", "Shadowed", "${KIPRJMOD}/mine.kicad_sym")

    assert load_tables(SYMBOLS, mini_env, mini).find("Shadowed") == mini / "mine.kicad_sym"


def test_finds_pcm_package_missing_from_tables(mini: Path, mini_env: KicadEnv) -> None:
    found = load_tables(FOOTPRINTS, mini_env, mini).find("PCM_Mini_Pkg")

    assert found == MINI / "3rdparty/footprints/com_example_mini/Mini_Pkg.pretty"


def test_returns_nothing_for_unknown_library(mini: Path, mini_env: KicadEnv) -> None:
    tables = load_tables(FOOTPRINTS, mini_env, mini)

    assert tables.find("Nope") is None
    assert tables.find("PCM_Nope") is None


def test_raises_if_pcm_library_is_in_two_packages(
    tmp_path: Path, mini: Path, mini_env: KicadEnv
) -> None:
    third = tmp_path / "3rdparty"
    shutil.copytree(MINI / "3rdparty", third)
    shutil.copytree(third / "footprints/com_example_mini", third / "footprints/com_example_copy")
    env = with_variable(mini_env, "KICAD10_3RD_PARTY", str(third))

    with pytest.raises(AdoptError, match="ambiguous"):
        load_tables(FOOTPRINTS, env, mini).find("PCM_Mini_Pkg")
