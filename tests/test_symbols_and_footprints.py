# Adopting explicitly named parts: -sf, -s and -f, and how parent symbols come along.

import shutil
from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from kiadopt.symbols import SymbolLib, footprint_field, order_parents_first, with_parents
from tests.conftest import Adopt
from tests.helpers import (
    ACME_SYMBOLS,
    FakeWeb,
    actions,
    library_symbols,
    read,
    register_library,
    subjects,
    targets,
)


def test_copies_symbol_with_parent_footprint_and_model(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Regulator:LDO_B"])

    assert subjects(result, "symbol") == ["PCM_ACME_Regulator:LDO_A", "PCM_ACME_Regulator:LDO_B"]
    assert targets(result, "footprint") == ["libs/Local.pretty/SOIC-8.kicad_mod"]
    assert targets(result, "3D model") == ["libs/Local.3dshapes/SOIC-8.wrl"]
    assert (demo / "libs/Local.3dshapes/SOIC-8.wrl").is_file()
    footprint = read(demo / "libs/Local.pretty/SOIC-8.kicad_mod")
    assert '(model "${KIPRJMOD}/libs/Local.3dshapes/SOIC-8.wrl"' in footprint


def test_writes_parent_before_derived_symbol(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Regulator:LDO_B"])

    symbols = library_symbols(demo)
    assert list(symbols) == ["Existing", "LDO_A", "LDO_B"]
    assert '(extends "LDO_A")' in symbols["LDO_B"]


def test_points_footprint_field_at_copied_footprint(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Regulator:LDO_B"])

    assert '"Footprint" "Local:SOIC-8"' in library_symbols(demo)["LDO_B"]


def test_rewrites_footprint_filters_of_adopted_library(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(mini, mini_env, symbol_footprints=["PCM_Mini_Parts:Base"])

    filters = '"ki_fp_filters" "Local:QFN* Package_DFN:DFN*"'
    assert filters in library_symbols(mini)["Base"]


def test_takes_footprint_inherited_from_parent(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(mini, mini_env, symbol_footprints=["PCM_Mini_Parts:Derived"])

    assert subjects(result, "footprint") == ["PCM_Mini_Pkg:QFN-4"]
    assert actions(result, "footprint")[0].users == ("Base",)


def test_raises_if_footprint_field_is_empty(mini: Path, mini_env: KicadEnv, web: FakeWeb) -> None:
    request = Request(mini, "Local", symbol_footprints=["PCM_Mini_Parts:Lonely"])

    with pytest.raises(AdoptError, match="Lonely has an empty Footprint field"):
        plan(request, mini_env, web)


def test_leaves_footprint_field_and_filters_as_is(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, symbols=["PCM_ACME_Regulator:LDO_A"])

    assert subjects(result, "symbol") == ["PCM_ACME_Regulator:LDO_A"]
    assert actions(result, "footprint") == []
    symbol = library_symbols(demo)["LDO_A"]
    assert '"Footprint" "PCM_ACME_Package_SO:SOIC-8"' in symbol
    assert '"ki_fp_filters" "PCM_ACME_Package_SO:SOIC-8* SOT?23*"' in symbol


def test_copies_datasheet_if_asked(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    adopt(demo, demo_env, symbols=["PCM_ACME_Sensor:Sensor"], datasheets_dir=demo / "docs")

    assert '"Datasheet" "${KIPRJMOD}/docs/sensor.pdf"' in library_symbols(demo)["Sensor"]


def test_reads_folder_library(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    folder = demo / "vendor.kicad_sym"
    folder.mkdir()
    shutil.copy(ACME_SYMBOLS / "ACME_Sensor.kicad_sym", folder / "Sensor.kicad_sym")
    register_library(demo, "sym-lib-table", "Vendor", "${KIPRJMOD}/vendor.kicad_sym")

    result = adopt(demo, demo_env, symbols=["Vendor:Sensor"])

    assert subjects(result, "symbol") == ["Vendor:Sensor"]
    assert "Sensor" in library_symbols(demo)


def test_copies_footprint_with_model(mini: Path, mini_env: KicadEnv, adopt: Adopt) -> None:
    result = adopt(mini, mini_env, footprints=["PCM_Mini_Pkg:QFN-4"])

    assert actions(result, "symbol") == []
    assert actions(result, "footprint")[0].users == ()
    footprint = read(mini / "libs/Local.pretty/QFN-4.kicad_mod")
    assert '(model "${KIPRJMOD}/libs/Local.3dshapes/QFN-4.step"' in footprint


def test_does_not_create_symbol_library(mini: Path, mini_env: KicadEnv, adopt: Adopt) -> None:
    adopt(mini, mini_env, footprints=["PCM_Mini_Pkg:QFN-4"])

    assert not (mini / "libs/Local.kicad_sym").exists()


def test_copies_datasheet_from_field_and_description(
    mini: Path, mini_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    adopt(mini, mini_env, footprints=["PCM_Mini_Pkg:QFN-4"], datasheets_dir=mini / "docs")

    footprint = read(mini / "libs/Local.pretty/QFN-4.kicad_mod")
    assert '(descr "QFN 4 pins, ${KIPRJMOD}/docs/qfn.pdf")' in footprint
    assert '(property "Datasheet" "${KIPRJMOD}/docs/qfn.pdf"' in footprint
    assert web.requests == ["https://example.com/mini/qfn.pdf"]


def block(name: str, extends: str | None = None, footprint: str | None = None) -> str:
    lines = [f'\t(symbol "{name}"']
    if extends:
        lines.append(f'\t\t(extends "{extends}")')
    if footprint is not None:
        lines.append(f'\t\t(property "Footprint" "{footprint}")')
    return "\n".join(lines) + "\n\t)"


def library(*blocks: str) -> SymbolLib:
    return SymbolLib("", {text.split('"')[1]: text for text in blocks})


def test_collects_whole_extends_chain() -> None:
    lib = library(block("A", "B"), block("B", "C"), block("C"))

    assert with_parents(lib, "A") == ["A", "B", "C"]


def test_orders_parents_before_children() -> None:
    blocks = {"A": block("A", "C"), "B": block("B"), "C": block("C", "B")}

    assert order_parents_first(blocks) == ["B", "C", "A"]


def test_survives_extends_loop() -> None:
    lib = library(block("A", "B"), block("B", "A"))

    assert with_parents(lib, "A") == ["A", "B"]
    assert sorted(order_parents_first(lib.blocks)) == ["A", "B"]


def test_inherits_footprint_field_from_parent() -> None:
    lib = library(block("Child", "Base"), block("Base", footprint="Pkg:SO8"))

    assert footprint_field(lib, "Child") == "Pkg:SO8"


def test_has_empty_footprint_if_parent_is_missing() -> None:
    assert footprint_field(library(block("Orphan", "Gone")), "Orphan") == ""
