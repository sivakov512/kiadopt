# Parts that are already in the target library, including a repeated run.

from pathlib import Path
from typing import Any

from kiadopt import KicadEnv, Request, plan
from tests.conftest import Adopt
from tests.helpers import FakeWeb, read, snapshot, subjects


def test_skips_parts_already_in_library(
    demo: Path, demo_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Sensor:Sensor"])

    result = plan(
        Request(demo, "Local", symbol_footprints=["PCM_ACME_Sensor:Sensor"]), demo_env, web
    )

    assert [(action.subject, action.detail) for action in result.actions] == [
        ("libs/Local.3dshapes/DFN-6.wrl", "already exists"),
        ("Local:Sensor", "already in Local"),
        ("Local:DFN-6", "already in Local"),
    ]
    assert not result.has_changes


def test_keeps_edited_parts_and_warns(
    demo: Path, demo_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    adopt(demo, demo_env, symbol_footprints=["PCM_ACME_Sensor:Sensor"])
    library = demo / "libs/Local.kicad_sym"
    library.write_text(read(library).replace("Temperature sensor", "Edited by hand"))
    footprint = demo / "libs/Local.pretty/DFN-6.kicad_mod"
    footprint.write_text(read(footprint).replace("DFN, 6 pins", "DFN six"))

    result = plan(
        Request(demo, "Local", symbol_footprints=["PCM_ACME_Sensor:Sensor"]), demo_env, web
    )

    assert result.warnings == [
        "Local:Sensor differs from the adopted part; kept the existing one",
        "Local:DFN-6 differs from the adopted part; kept the existing one",
    ]
    assert not result.has_changes


def test_skips_parts_taken_from_target_library_itself(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    result = plan(Request(demo, "Local", symbol_footprints=["Local:Existing"]), demo_env, web)

    assert subjects(result, "skip") == ["Local:Existing", "Local:Existing_FP"]
    assert not result.has_changes


def test_from_prefix_again_changes_nothing(
    demo: Path, demo_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    options: dict[str, Any] = {
        "prefixes": ["PCM_ACME"],
        "datasheets_dir": demo / "docs",
        "update_project": True,
    }
    adopt(demo, demo_env, **options)
    before = snapshot(demo)

    result = plan(Request(demo, "Local", **options), demo_env, web)

    assert not result.has_changes
    assert result.actions == []
    assert snapshot(demo) == before
