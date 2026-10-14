from datetime import datetime
from pathlib import Path

import pytest

from kiadopt import KicadEnv, Plan, Request, apply, plan
from tests.helpers import FakeWeb, snapshot

NOW = datetime(2026, 10, 13, 12, 0, 0)


@pytest.fixture
def adoption(demo: Path, demo_env: KicadEnv, web: FakeWeb) -> Plan:
    return plan(Request(demo, "Local", prefixes=["PCM_ACME"], update_project=True), demo_env, web)


def test_backs_up_every_file_it_changes(demo: Path, adoption: Plan) -> None:
    original = snapshot(demo)

    applied = apply(adoption, now=NOW)

    backup = demo / "demo-backups/adopt-20261013-120000"
    assert applied.backup_dir == backup
    assert snapshot(backup) == {
        name: original[name]
        for name in (
            "channel.kicad_sch",
            "demo.kicad_pcb",
            "demo.kicad_sch",
            "libs/Local.kicad_sym",
        )
    }


def test_makes_no_backup_if_only_new_files_are_written(
    mini: Path, mini_env: KicadEnv, web: FakeWeb
) -> None:
    result = plan(Request(mini, "Local", footprints=["PCM_Mini_Pkg:QFN-4"]), mini_env, web)

    assert apply(result, now=NOW).backup_dir is None
    assert not (mini / "mini-backups").exists()


def test_backs_up_file_outside_project_by_absolute_path(
    tmp_path: Path, demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    result = plan(Request(demo, "Local", symbols=["PCM_ACME_Sensor:Sensor"]), demo_env, web)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("old")
    result.texts[outside] = "new"

    applied = apply(result, now=NOW)

    assert applied.backup_dir is not None
    assert (applied.backup_dir / outside.relative_to(outside.anchor)).read_text() == "old"
    assert outside.read_text() == "new"


def test_changes_nothing_if_a_write_fails(demo: Path, adoption: Plan) -> None:
    before = snapshot(demo)
    footprints = demo / "libs/Local.pretty"
    footprints.chmod(0o555)

    try:
        with pytest.raises(PermissionError):
            apply(adoption, now=NOW)
    finally:
        footprints.chmod(0o755)

    assert snapshot(demo) == before


def test_changes_nothing_if_backup_fails(demo: Path, adoption: Plan) -> None:
    (demo / "demo-backups").write_text("not a folder")
    before = snapshot(demo)

    with pytest.raises(OSError):
        apply(adoption, now=NOW)

    assert snapshot(demo) == before
