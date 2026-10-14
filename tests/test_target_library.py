from pathlib import Path
from typing import Any

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from tests.conftest import Adopt
from tests.helpers import ACME_SYMBOLS, FakeWeb, actions, library_symbols, read


def test_creates_and_registers_new_library_in_libs(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, "Adopted", symbol_footprints=["PCM_ACME_Sensor:Sensor"])

    registered = [(action.subject, action.target) for action in actions(result, "register")]
    assert registered == [("Adopted", "sym-lib-table"), ("Adopted", "fp-lib-table")]
    assert list(library_symbols(demo, "Adopted")) == ["Sensor"]
    assert '(uri "${KIPRJMOD}/libs/Adopted.kicad_sym")' in read(demo / "sym-lib-table")
    assert '(uri "${KIPRJMOD}/libs/Adopted.pretty")' in read(demo / "fp-lib-table")
    assert (demo / "libs/Adopted.3dshapes/DFN-6.wrl").is_file()


def test_new_library_takes_header_from_source_library(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(demo, demo_env, "Adopted", symbols=["PCM_ACME_Sensor:Sensor"])

    header = read(demo / "libs/Adopted.kicad_sym").split("\t(symbol")[0]
    assert header == read(ACME_SYMBOLS / "ACME_Sensor.kicad_sym").split("\t(symbol")[0]


def test_creates_library_and_tables_in_lib_dir(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(mini, mini_env, "Mine", symbol_footprints=["PCM_Mini_Parts:Base"], lib_dir=mini / "parts")

    assert read(mini / "sym-lib-table") == (
        "(sym_lib_table\n\t(version 7)\n"
        '\t(lib (name "Mine") (type "KiCad") (uri "${KIPRJMOD}/parts/Mine.kicad_sym")'
        ' (options "") (descr ""))\n)\n'
    )
    assert (mini / "parts/Mine.pretty/QFN-4.kicad_mod").is_file()
    assert (mini / "parts/Mine.3dshapes/QFN-4.step").is_file()


def test_uses_registered_paths_and_ignores_lib_dir(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(
        demo, demo_env, footprints=["PCM_ACME_Package_DFN:DFN-6"], lib_dir=demo / "ignored"
    )

    assert actions(result, "register") == []
    assert not (demo / "ignored").exists()


@pytest.mark.parametrize(
    ("target", "options", "message"),
    [
        ("PCM_ACME_Sensor", {}, "global library"),
        ("Local", {"prefixes": ["Local"]}, "one of the --from libraries"),
        ("Bad:Name", {}, "invalid library name"),
        ("Elsewhere", {"lib_dir": Path("/tmp/kiadopt-outside")}, "must be inside the project"),
    ],
    ids=["global", "same-as-from", "with-colon", "outside-project"],
)
def test_refuses_unsuitable_target(
    demo: Path,
    demo_env: KicadEnv,
    web: FakeWeb,
    target: str,
    options: dict[str, Any],
    message: str,
) -> None:
    request = Request(demo, target, symbols=["PCM_ACME_Sensor:Sensor"], **options)

    with pytest.raises(AdoptError, match=message):
        plan(request, demo_env, web)


def test_refuses_target_of_non_kicad_type(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    table = demo / "sym-lib-table"
    table.write_text(read(table).replace('(type "KiCad")', '(type "Legacy")'))

    with pytest.raises(AdoptError, match="has type Legacy, expected KiCad"):
        plan(Request(demo, "Local", symbols=["PCM_ACME_Sensor:Sensor"]), demo_env, web)


def test_refuses_folder_library_as_target(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    (demo / "libs/Folder.kicad_sym").mkdir()

    with pytest.raises(AdoptError, match="folder libraries not supported"):
        plan(Request(demo, "Folder", symbols=["PCM_ACME_Sensor:Sensor"]), demo_env, web)
