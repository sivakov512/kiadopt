import shutil
from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from tests.helpers import ACME, ACME_FOOTPRINTS, ACME_SYMBOLS, FakeWeb, editable_third_party


def test_raises_if_nothing_is_asked(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    with pytest.raises(AdoptError, match="nothing to adopt"):
        plan(Request(demo, "Local"), demo_env, web)


def test_reports_all_missing_parts_at_once(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    request = Request(
        demo,
        "Local",
        symbol_footprints=["PCM_ACME_Regulator:Nope"],
        symbols=["Nowhere:X"],
        footprints=["PCM_ACME_Package_SO:Nope", "Nowhere:Y"],
    )

    with pytest.raises(AdoptError) as error:
        plan(request, demo_env, web)

    assert error.value.messages == (
        "symbol Nowhere:X not found: library Nowhere not found",
        "symbol PCM_ACME_Regulator:Nope not found:"
        f" not in {ACME_SYMBOLS / 'ACME_Regulator.kicad_sym'}",
        "footprint Nowhere:Y not found: library Nowhere not found",
        "footprint PCM_ACME_Package_SO:Nope not found:"
        f" no {ACME_FOOTPRINTS / 'ACME_Package_SO.pretty/Nope.kicad_mod'}",
    )


def test_raises_if_footprint_of_symbol_is_missing(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    third, env = editable_third_party(demo, demo_env)
    (third / f"footprints/{ACME}/ACME_Package_DFN.pretty/DFN-6.kicad_mod").unlink()
    request = Request(demo, "Local", symbol_footprints=["PCM_ACME_Sensor:Sensor"])

    with pytest.raises(AdoptError, match="footprint PCM_ACME_Package_DFN:DFN-6 not found"):
        plan(request, env, web)


def test_reports_ambiguous_pcm_library_with_other_problems(
    mini: Path, mini_env: KicadEnv, web: FakeWeb
) -> None:
    third, env = editable_third_party(mini, mini_env)
    shutil.copytree(third / "footprints/com_example_mini", third / "footprints/com_example_fork")
    request = Request(mini, "Local", footprints=["PCM_Mini_Pkg:QFN-4"], symbols=["Nowhere:X"])

    with pytest.raises(AdoptError) as error:
        plan(request, env, web)

    assert error.value.messages[0] == "symbol Nowhere:X not found: library Nowhere not found"
    assert error.value.messages[1].startswith("library PCM_Mini_Pkg is ambiguous: ")


@pytest.mark.parametrize(
    "broken", ["sym-lib-table", "libs/Local.kicad_sym", "libs/Local.pretty/Existing_FP.kicad_mod"]
)
def test_names_broken_file(demo: Path, demo_env: KicadEnv, web: FakeWeb, broken: str) -> None:
    (demo / broken).write_text("(unfinished")
    request = Request(demo, "Local", symbol_footprints=["Local:Existing"])

    with pytest.raises(AdoptError, match=rf"{broken}: unexpected end"):
        plan(request, demo_env, web)
