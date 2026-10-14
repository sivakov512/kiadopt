from pathlib import Path

import pytest

from kiadopt import AdoptError, KicadEnv, Request, plan
from tests.conftest import Adopt
from tests.helpers import (
    ACME,
    FakeWeb,
    editable_third_party,
    library_symbols,
    read,
    subjects,
)


def test_takes_symbols_and_footprints_the_project_uses(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"])

    assert subjects(result, "symbol") == [
        "PCM_ACME_Regulator:LDO_A",
        "PCM_ACME_Regulator:LDO_B",
        "PCM_ACME_Regulator:LDO_C",
        "PCM_ACME_Sensor:Sensor",
    ]
    assert subjects(result, "footprint") == [
        "PCM_ACME_Passive:C_0805_Special",
        "PCM_ACME_Package_DFN:DFN-6",
        "PCM_ACME_Package_SO:SOIC-8",
        "PCM_ACME_Package_SO:SOIC-8_EP",
    ]


def test_matches_whole_nickname_parts_only(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    result = plan(Request(demo, "Local", prefixes=["PCM_AC"]), demo_env, web)

    assert result.actions == []
    assert not result.has_changes


def test_keeps_footprint_from_another_library(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    third, env = editable_third_party(demo, demo_env)
    library = third / f"symbols/{ACME}/ACME_Regulator.kicad_sym"
    stock = "Capacitor_SMD:C_0805_2012Metric"
    library.write_text(read(library).replace('"PCM_ACME_Package_SO:SOIC-8_EP"', f'"{stock}"'))

    result = adopt(demo, env, prefixes=["PCM_ACME"])

    assert stock not in subjects(result, "footprint")
    assert f'"Footprint" "{stock}"' in library_symbols(demo)["LDO_C"]


def test_takes_symbol_from_schematic_if_library_lost_it(
    mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(mini, mini_env, prefixes=["PCM_Mini_Gone"])

    assert subjects(result, "symbol") == ["PCM_Mini_Gone:Ghost"]
    assert result.warnings == [
        "symbol PCM_Mini_Gone:Ghost not found in its library; copied from the schematic"
    ]
    symbol = library_symbols(mini)["Ghost"]
    assert symbol.startswith('\t(symbol "Ghost"\n\t\t(property "Reference" "U"')
    assert '\t\t(symbol "Ghost_1_1"\n' in symbol
    assert '(generator "kiadopt")' in read(mini / "libs/Local.kicad_sym")


def test_raises_if_symbol_is_neither_in_library_nor_in_schematic(
    mini: Path, mini_env: KicadEnv, web: FakeWeb
) -> None:
    sheet = mini / "sub.kicad_sch"
    sheet.write_text(read(sheet).replace('(symbol "PCM_Mini_Gone:Ghost"', '(symbol "Cache:Other"'))

    with pytest.raises(AdoptError, match="Ghost not found in its library or the schematic"):
        plan(Request(mini, "Local", prefixes=["PCM_Mini_Gone"]), mini_env, web)
