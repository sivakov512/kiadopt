import shutil
from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from tests.conftest import Adopt
from tests.helpers import (
    ACME,
    FakeWeb,
    actions,
    editable_third_party,
    read,
    register_library,
    targets,
)


def test_copies_to_folder_given_with_models_option(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(
        demo, demo_env, footprints=["PCM_ACME_Package_DFN:DFN-6"], models_dir=demo / "3d"
    )

    assert targets(result, "3D model") == ["3d/DFN-6.wrl"]
    assert '"${KIPRJMOD}/3d/DFN-6.wrl"' in read(demo / "libs/Local.pretty/DFN-6.kicad_mod")


def test_refers_to_folder_outside_project_by_absolute_path(
    tmp_path: Path, demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    outside = tmp_path / "shared-models"

    adopt(demo, demo_env, footprints=["PCM_ACME_Package_DFN:DFN-6"], models_dir=outside)

    assert (outside / "DFN-6.wrl").is_file()
    footprint = read(demo / "libs/Local.pretty/DFN-6.kicad_mod")
    assert f'(model "{outside.as_posix()}/DFN-6.wrl"' in footprint


def test_warns_and_keeps_path_of_missing_model(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    model = f"3dmodels/{ACME}/ACME_Package_DFN.3dshapes/DFN-6.wrl"
    third, env = editable_third_party(demo, demo_env)
    (third / model).unlink()

    result = plan(Request(demo, "Local", footprints=["PCM_ACME_Package_DFN:DFN-6"]), env, web)

    assert result.warnings == [
        f"3D model not found, path kept: ${{KICAD10_3RD_PARTY}}/{model} (DFN-6)"
    ]
    assert actions(result, "3D model") == []


def test_leaves_project_and_embedded_models_alone(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    (demo / "parts.pretty").mkdir()
    source = demo / "parts.pretty/P.kicad_mod"
    source.write_text(
        '(footprint "P" (layer "F.Cu")\n'
        '\t(model "${KIPRJMOD}/libs/Local.3dshapes/Existing.wrl")\n'
        '\t(model "kicad-embed://p.step")\n)\n'
    )
    register_library(demo, "fp-lib-table", "Parts", "${KIPRJMOD}/parts.pretty")

    result = adopt(demo, demo_env, footprints=["Parts:P"])

    assert actions(result, "3D model") == []
    assert read(demo / "libs/Local.pretty/P.kicad_mod") == read(source)


def test_copies_model_found_only_on_board(mini: Path, mini_env: KicadEnv, adopt: Adopt) -> None:
    third, env = editable_third_party(mini, mini_env)
    shutil.copy(
        third / "3dmodels/com_example_mini/QFN-4.step",
        third / "3dmodels/com_example_mini/Board.step",
    )
    board = mini / "mini.kicad_pcb"
    text = read(board)
    cut = text.index('\t\t(model "${KICAD8_3RD_PARTY}')
    extra = '\t\t(model "${KICAD10_3RD_PARTY}/3dmodels/com_example_mini/Board.step")\n'
    board.write_text(text[:cut] + extra + text[cut:])

    result = adopt(mini, env, footprints=["PCM_Mini_Pkg:QFN-4"], update_project=True)

    assert targets(result, "3D model") == [
        "libs/Local.3dshapes/Board.step",
        "libs/Local.3dshapes/QFN-4.step",
    ]
    assert '(model "${KIPRJMOD}/libs/Local.3dshapes/Board.step")' in read(board)


def test_raises_if_different_models_share_name(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    third, env = editable_third_party(demo, demo_env)
    (third / f"3dmodels/{ACME}/ACME_Passive.3dshapes/SOIC-8.wrl").write_text("different")
    footprint = third / f"footprints/{ACME}/ACME_Passive.pretty/C_0805_Special.kicad_mod"
    footprint.write_text(read(footprint).replace("C_0805_Special.wrl", "SOIC-8.wrl"))
    footprints = ["PCM_ACME_Package_SO:SOIC-8", "PCM_ACME_Passive:C_0805_Special"]

    with pytest.raises(AdoptError, match=r"3D model conflict: .* both map to"):
        plan(Request(demo, "Local", footprints=footprints), env, web)


def test_raises_if_other_model_with_same_name_exists(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    (demo / "libs/Local.3dshapes/SOIC-8.wrl").write_text("mine")

    with pytest.raises(AdoptError, match=r"SOIC-8\.wrl already exists with other content"):
        plan(Request(demo, "Local", footprints=["PCM_ACME_Package_SO:SOIC-8"]), demo_env, web)
