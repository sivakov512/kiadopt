import shutil
from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from tests.conftest import Adopt
from tests.helpers import (
    ACME_FOOTPRINTS,
    ACME_SYMBOLS,
    FakeWeb,
    actions,
    read,
    register_library,
    subjects,
)


def test_copies_shared_dependency_once_and_lists_its_users(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"], datasheets_dir=demo / "docs")

    users = {action.subject: action.users for action in result.actions}
    assert users["PCM_ACME_Regulator:LDO_A"] == ("LDO_B", "LDO_C")
    assert users["PCM_ACME_Package_SO:SOIC-8"] == ("LDO_A", "LDO_B")
    models = {action.target: action.users for action in actions(result, "3D model")}
    assert models["libs/Local.3dshapes/SOIC-8.wrl"] == ("SOIC-8", "SOIC-8_EP")
    datasheets = {action.target: action.users for action in actions(result, "datasheet")}
    assert datasheets["docs/ldo.pdf"] == ("LDO_A", "LDO_B")


def test_points_old_and_new_model_paths_at_one_copy(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    footprints = ["PCM_ACME_Package_SO:SOIC-8", "PCM_ACME_Package_SO:SOIC-8_EP"]

    adopt(demo, demo_env, footprints=footprints)

    for name in ("SOIC-8", "SOIC-8_EP"):
        footprint = read(demo / f"libs/Local.pretty/{name}.kicad_mod")
        assert '(model "${KIPRJMOD}/libs/Local.3dshapes/SOIC-8.wrl"' in footprint
    models = sorted(path.name for path in (demo / "libs/Local.3dshapes").iterdir())
    assert models == ["Existing.wrl", "SOIC-8.wrl"]


def test_reuses_and_relinks_to_what_previous_run_copied(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Regulator:LDO_A"], update_project=True)
    footprint = read(demo / "libs/Local.pretty/SOIC-8.kicad_mod")

    result = adopt(
        demo, demo_env, symbol_footprints=["PCM_ACME_Regulator:LDO_B"], update_project=True
    )

    assert subjects(result, "symbol") == ["PCM_ACME_Regulator:LDO_B"]
    assert subjects(result, "skip") == [
        "libs/Local.3dshapes/SOIC-8.wrl",
        "Local:LDO_A",
        "Local:SOIC-8",
    ]
    assert result.warnings == []
    assert read(demo / "libs/Local.pretty/SOIC-8.kicad_mod") == footprint
    sheet = read(demo / "demo.kicad_sch")
    assert "PCM_ACME_Regulator" not in sheet
    assert sheet.count('"Footprint" "Local:SOIC-8"') == 4
    board = read(demo / "demo.kicad_pcb")
    assert '(footprint "PCM_ACME_Package_SO:SOIC-8"' not in board
    assert board.count('(model "${KIPRJMOD}/libs/Local.3dshapes/SOIC-8.wrl"') == 2


def test_copies_equal_symbols_from_two_libraries_once(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    shutil.copy(ACME_SYMBOLS / "ACME_Sensor.kicad_sym", demo / "twin.kicad_sym")
    register_library(demo, "sym-lib-table", "Twin", "${KIPRJMOD}/twin.kicad_sym")
    request = Request(demo, "Local", symbols=["PCM_ACME_Sensor:Sensor", "Twin:Sensor"])

    result = plan(request, demo_env, web)

    assert subjects(result, "symbol") == ["PCM_ACME_Sensor:Sensor"]


def test_copies_equal_footprints_from_two_libraries_once(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    shutil.copytree(ACME_FOOTPRINTS / "ACME_Package_SO.pretty", demo / "twin.pretty")
    register_library(demo, "fp-lib-table", "Twin", "${KIPRJMOD}/twin.pretty")
    request = Request(demo, "Local", footprints=["PCM_ACME_Package_SO:SOIC-8", "Twin:SOIC-8"])

    result = plan(request, demo_env, web)

    assert subjects(result, "footprint") == ["PCM_ACME_Package_SO:SOIC-8"]


def test_raises_if_different_symbols_share_name(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    text = read(ACME_SYMBOLS / "ACME_Sensor.kicad_sym")
    (demo / "twin.kicad_sym").write_text(text.replace("Temperature sensor", "Humidity sensor"))
    register_library(demo, "sym-lib-table", "Twin", "${KIPRJMOD}/twin.kicad_sym")
    request = Request(demo, "Local", symbols=["PCM_ACME_Sensor:Sensor", "Twin:Sensor"])

    with pytest.raises(AdoptError, match="symbols PCM_ACME_Sensor:Sensor and Twin:Sensor differ"):
        plan(request, demo_env, web)


def test_raises_if_different_footprints_share_name(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    (demo / "twin.pretty").mkdir()
    (demo / "twin.pretty/SOIC-8.kicad_mod").write_text('(footprint "SOIC-8" (layer "F.Cu"))')
    register_library(demo, "fp-lib-table", "Twin", "${KIPRJMOD}/twin.pretty")
    request = Request(demo, "Local", footprints=["PCM_ACME_Package_SO:SOIC-8", "Twin:SOIC-8"])

    with pytest.raises(AdoptError, match="footprints PCM_ACME_Package_SO:SOIC-8 and Twin:SOIC-8"):
        plan(request, demo_env, web)
