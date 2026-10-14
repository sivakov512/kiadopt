from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from kiadopt.document import parse_document
from kiadopt.relink import Relink, schematic_text
from tests.conftest import Adopt
from tests.helpers import FakeWeb, actions, read

RELINK = Relink(
    target="Local",
    symbols={"Vendor:Chip": "Local:Chip"},
    footprints={"Vendor:SO8": "Local:SO8"},
    models={},
    datasheets={},
)


def test_relinks_every_sheet_and_board(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"], update_project=True)

    assert [(action.subject, action.detail) for action in actions(result, "relink")] == [
        ("demo.kicad_sch", "(11 references)"),
        ("channel.kicad_sch", "(10 references)"),
        ("demo.kicad_pcb", "(14 references)"),
    ]
    sheets = read(demo / "demo.kicad_sch") + read(demo / "channel.kicad_sch")
    assert "PCM_ACME" not in sheets
    assert "PCM_ACME" not in read(demo / "demo.kicad_pcb")


def test_leaves_parts_of_other_libraries_alone(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(demo, demo_env, prefixes=["PCM_ACME"], update_project=True)

    sheets = read(demo / "demo.kicad_sch") + read(demo / "channel.kicad_sch")
    assert '(lib_id "PCM_Other_Misc:Thing")' in sheets
    assert '(lib_id "Device:R")' in sheets
    board = read(demo / "demo.kicad_pcb")
    assert '(footprint "PCM_Other_Misc:Thing_FP"' in board
    assert "${KICAD10_3RD_PARTY}/3dmodels/com_github_other_kicad-library" in board


def test_relinks_adopted_footprint_of_stock_symbol(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(demo, demo_env, prefixes=["PCM_ACME"], update_project=True)

    sheet = read(demo / "demo.kicad_sch")
    assert '(lib_id "Device:C")' in sheet
    assert '"Footprint" "Local:C_0805_Special"' in sheet


def test_leaves_project_files_alone_without_flag(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    names = ("demo.kicad_sch", "channel.kicad_sch", "demo.kicad_pcb")
    before = {name: read(demo / name) for name in names}

    result = adopt(demo, demo_env, prefixes=["PCM_ACME"])

    assert actions(result, "relink") == []
    assert {name: read(demo / name) for name in names} == before


def test_refuses_while_project_is_open_in_kicad(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    (demo / "~demo.kicad_sch.lck").write_text("{}")
    request = Request(demo, "Local", prefixes=["PCM_ACME"], update_project=True)

    with pytest.raises(AdoptError, match=r"open in KiCad \(~demo\.kicad_sch\.lck\); close KiCad"):
        plan(request, demo_env, web)


def test_ignores_lock_files_without_flag(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    (demo / "~demo.kicad_sch.lck").write_text("{}")

    assert plan(Request(demo, "Local", prefixes=["PCM_ACME"]), demo_env, web).has_changes


def test_notices_lock_file_next_to_sheet_in_subfolder(
    mini: Path, mini_env: KicadEnv, web: FakeWeb
) -> None:
    (mini / "sheets").mkdir()
    (mini / "sub.kicad_sch").rename(mini / "sheets/sub.kicad_sch")
    root = mini / "mini.kicad_sch"
    root.write_text(read(root).replace('"sub.kicad_sch"', '"sheets/sub.kicad_sch"'))
    (mini / "sheets/~sub.kicad_sch.lck").write_text("{}")
    request = Request(mini, "Local", prefixes=["PCM_Mini"], update_project=True)

    with pytest.raises(AdoptError, match=r"sheets/~sub\.kicad_sch\.lck"):
        plan(request, mini_env, web)


def test_keeps_crlf_line_endings_and_non_ascii_text(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    sheet = mini / "mini.kicad_sch"
    text = read(sheet).replace('"U1"', '"Стабилизатор U1"')
    sheet.write_bytes(text.replace("\n", "\r\n").encode())
    before = read(sheet)

    adopt(mini, mini_env, symbol_footprints=["PCM_Mini_Parts:Derived"], update_project=True)

    after = read(sheet)
    assert after.count("\r\n") == after.count("\n")
    restored = (
        after.replace("Local:Derived", "PCM_Mini_Parts:Derived")
        .replace("Local:QFN-4", "PCM_Mini_Pkg:QFN-4")
        .replace("Local:QFN*", "PCM_Mini_Pkg:QFN*")
    )
    assert restored == before


def test_drops_cached_copy_if_new_name_is_cached_already(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    sheet = mini / "mini.kicad_sch"
    text = read(sheet)
    start = text.index('\t\t(symbol "PCM_Mini_Parts:Derived"')
    end = text.index("\n\t\t)\n", start) + len("\n\t\t)\n")
    local_copy = text[start:end].replace('"PCM_Mini_Parts:Derived"', '"Local:Derived"')
    sheet.write_text(text[:start] + local_copy + text[start:])

    adopt(mini, mini_env, symbol_footprints=["PCM_Mini_Parts:Derived"], update_project=True)

    result = read(sheet)
    assert result.count('(symbol "Local:Derived"') == 1
    assert "PCM_Mini_Parts" not in result


def test_relinks_sheet_without_symbol_cache() -> None:
    text = '(kicad_sch\n\t(symbol (lib_id "Vendor:Chip") (property "Footprint" "Vendor:SO8"))\n)\n'

    new_text, count = schematic_text(parse_document(Path("a.kicad_sch"), text), RELINK)

    assert new_text == text.replace("Vendor:", "Local:")
    assert count == 2
