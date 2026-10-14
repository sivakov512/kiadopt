from pathlib import Path

import pytest

from kiadopt import KicadEnv, Plan, Request, plan
from kiadopt.assets import Placement, collect_datasheets
from kiadopt.fetch import _curl, fetch
from tests.conftest import Adopt
from tests.helpers import (
    ACME,
    PDF,
    FakeWeb,
    actions,
    editable_third_party,
    library_symbols,
    read,
)

SENSOR_PDF = f"${{KICAD10_3RD_PARTY}}/resources/{ACME}/sensor.pdf"


def test_downloads_pdf_links_and_copies_local_files(
    demo: Path, demo_env: KicadEnv, adopt: Adopt
) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"], datasheets_dir=demo / "docs")

    assert {action.subject: action.target for action in actions(result, "datasheet")} == {
        SENSOR_PDF: "docs/sensor.pdf",
        "https://example.com/acme/dfn.pdf": "docs/dfn.pdf",
        "https://example.com/acme/ldo.pdf": "docs/ldo.pdf",
    }
    assert (demo / "docs/ldo.pdf").read_bytes() == PDF + b"ldo"
    assert '"Datasheet" "${KIPRJMOD}/docs/ldo.pdf"' in library_symbols(demo)["LDO_A"]


def test_keeps_link_if_download_is_not_pdf(demo: Path, demo_env: KicadEnv, adopt: Adopt) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"], datasheets_dir=demo / "docs")

    url = "https://example.com/acme/ldo-c.pdf"
    assert result.warnings == [f"datasheet is not a PDF, link kept: {url}"]
    assert f'"Datasheet" "{url}"' in library_symbols(demo)["LDO_C"]


def test_keeps_link_on_network_error(mini: Path, mini_env: KicadEnv) -> None:
    request = Request(
        mini, "Local", footprints=["PCM_Mini_Pkg:QFN-4"], datasheets_dir=mini / "docs"
    )

    result = plan(request, mini_env, FakeWeb())

    url = "https://example.com/mini/qfn.pdf"
    assert result.warnings == [f"datasheet download failed, link kept: {url}: cannot reach {url}"]
    assert result.blobs == {}


def test_downloads_each_url_once(
    demo: Path, demo_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    adopt(demo, demo_env, prefixes=["PCM_ACME"], datasheets_dir=demo / "docs")

    assert web.requests.count("https://example.com/acme/ldo.pdf") == 1


def test_ignores_empty_values(mini: Path, web: FakeWeb) -> None:
    placement = Placement(mini / "docs", mini, {})

    assets = collect_datasheets([("", "A"), ("~", "B")], placement, web)

    assert assets.items == []
    assert web.requests == []


def test_untouched_without_datasheets_option(
    demo: Path, demo_env: KicadEnv, adopt: Adopt, web: FakeWeb
) -> None:
    result = adopt(demo, demo_env, prefixes=["PCM_ACME"])

    assert actions(result, "datasheet") == []
    assert web.requests == []


def test_refers_to_folder_outside_project_by_absolute_path(
    tmp_path: Path, mini: Path, mini_env: KicadEnv, adopt: Adopt
) -> None:
    adopt(mini, mini_env, footprints=["PCM_Mini_Pkg:QFN-4"], datasheets_dir=tmp_path / "pdf")

    footprint = read(mini / "libs/Local.pretty/QFN-4.kicad_mod")
    assert f'"Datasheet" "{(tmp_path / "pdf").as_posix()}/qfn.pdf"' in footprint


def plan_sensor_with_datasheet(demo: Path, env: KicadEnv, value: str, web: FakeWeb) -> Plan:
    third, env = editable_third_party(demo, env)
    library = third / f"symbols/{ACME}/ACME_Sensor.kicad_sym"
    library.write_text(read(library).replace(SENSOR_PDF, value))
    request = Request(
        demo, "Local", symbols=["PCM_ACME_Sensor:Sensor"], datasheets_dir=demo / "docs"
    )
    return plan(request, env, web)


def test_leaves_local_file_inside_project_alone(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    result = plan_sensor_with_datasheet(demo, demo_env, "${KIPRJMOD}/docs/own.pdf", web)

    assert actions(result, "datasheet") == []
    assert '"Datasheet" "${KIPRJMOD}/docs/own.pdf"' in result.texts[demo / "libs/Local.kicad_sym"]


def test_warns_about_missing_local_file(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> None:
    result = plan_sensor_with_datasheet(demo, demo_env, "/nowhere/x.pdf", web)

    assert result.warnings == ["datasheet not found, link kept: /nowhere/x.pdf (Sensor)"]
    assert '"Datasheet" "/nowhere/x.pdf"' in result.texts[demo / "libs/Local.kicad_sym"]


def test_keeps_link_if_other_file_with_same_name_exists(
    demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    (demo / "docs").mkdir()
    (demo / "docs/ldo.pdf").write_bytes(PDF + b"someone else's")
    request = Request(
        demo, "Local", symbols=["PCM_ACME_Regulator:LDO_A"], datasheets_dir=demo / "docs"
    )

    result = plan(request, demo_env, web)

    assert result.warnings == [
        f"datasheet name clash, link kept: {demo / 'docs/ldo.pdf'} already exists"
        " with other content (https://example.com/acme/ldo.pdf)"
    ]


def test_shares_file_between_urls_with_equal_content(mini: Path) -> None:
    web = FakeWeb(
        {
            "https://a.example/x/doc.pdf": PDF + b"a",
            "https://b.example/doc.pdf": PDF + b"b",
            "https://c.example/doc": PDF + b"a",
        }
    )
    uses = [
        ("https://a.example/x/doc.pdf", "A"),
        ("https://b.example/doc.pdf", "B"),
        ("https://c.example/doc", "C"),
    ]

    assets = collect_datasheets(uses, Placement(mini / "docs", mini, {}), web)

    assert [(asset.source, sorted(asset.users)) for asset in assets.items] == [
        ("https://a.example/x/doc.pdf", ["A", "C"])
    ]
    assert assets.references["https://c.example/doc"] == "${KIPRJMOD}/docs/doc.pdf"
    assert assets.warnings == [
        "datasheet name clash, link kept: https://a.example/x/doc.pdf"
        f" and https://b.example/doc.pdf both map to {mini / 'docs/doc.pdf'}"
    ]


def test_downloads_with_urllib(tmp_path: Path) -> None:
    page = tmp_path / "doc.pdf"
    page.write_bytes(b"%PDF-1.7 local")

    assert fetch(page.as_uri()) == b"%PDF-1.7 local"


def test_curl_downloads_too(tmp_path: Path) -> None:
    page = tmp_path / "doc.pdf"
    page.write_bytes(b"%PDF-1.7 via curl")

    assert _curl(page.as_uri()) == b"%PDF-1.7 via curl"


def test_raises_curl_error_if_both_fail() -> None:
    with pytest.raises(OSError, match=r"(?i)protocol"):
        fetch("kiadopt-test://nowhere/doc.pdf")
