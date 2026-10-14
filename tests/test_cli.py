import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import pytest

from kiadopt.cli import build_parser, main
from tests.helpers import DEMO_KICAD, snapshot, stock_environ


@pytest.fixture
def environ(tmp_path: Path) -> dict[str, str]:
    return stock_environ(DEMO_KICAD, tmp_path / "home")


def test_parses_sf_as_its_own_option() -> None:
    args = build_parser().parse_args(["-sf", "A:B", "-s", "C:D", "-f", "E:F", "--to", "Local"])

    assert args.symbol_footprint == ["A:B"]
    assert args.symbol == ["C:D"]
    assert args.footprint == ["E:F"]


def test_accepts_repeated_options() -> None:
    args = build_parser().parse_args(
        [
            "-sf",
            "A:B",
            "--symbol-footprint",
            "G:H",
            "--from",
            "PCM_A",
            "--from",
            "PCM_B",
            "--to",
            "L",
        ]
    )

    assert args.symbol_footprint == ["A:B", "G:H"]
    assert args.prefixes == ["PCM_A", "PCM_B"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [([], None), (["--datasheets"], "docs"), (["--datasheets", "pdf"], "pdf")],
    ids=["off", "default-folder", "given-folder"],
)
def test_parses_optional_datasheets_folder(argv: list[str], expected: str | None) -> None:
    datasheets = build_parser().parse_args(["--to", "L", *argv]).datasheets

    assert (str(datasheets) if datasheets else None) == expected


@pytest.mark.parametrize(
    "argv",
    [["--to", "Local"], ["-s", "Device:R"], ["-s", "Device:R", "--to", "Local", "--bogus"]],
    ids=["nothing-to-adopt", "no-target", "unknown-option"],
)
def test_exits_with_2_on_bad_arguments(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(argv)

    assert error.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_prints_one_line_per_action_and_backup(
    demo: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["-sf", "PCM_ACME_Sensor:Sensor", "--to", "Local", "--project", str(demo)]

    assert main(argv, environ) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "symbol     PCM_ACME_Sensor:Sensor  ->  libs/Local.kicad_sym"
    assert out[1] == (
        "footprint  PCM_ACME_Package_DFN:DFN-6  ->  libs/Local.pretty/DFN-6.kicad_mod  (Sensor)"
    )
    assert out[2].startswith("3D model   ${KICAD10_3RD_PARTY}/3dmodels/")
    assert out[2].endswith("DFN-6.wrl  ->  libs/Local.3dshapes/DFN-6.wrl  (DFN-6)")
    assert out[3].startswith("Backup: demo-backups/adopt-")
    assert len(out) == 4


def test_prints_no_backup_line_if_only_new_files_are_written(
    demo: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["-f", "PCM_ACME_Package_DFN:DFN-6", "--to", "Local", "--project", str(demo)]

    assert main(argv, environ) == 0

    assert "Backup:" not in capsys.readouterr().out


def test_resolves_relative_paths_from_current_folder(
    demo: Path, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(demo / "libs")
    argv = ["-sf", "PCM_ACME_Sensor:Sensor", "--to", "Local", "--project", ".."]

    # The sensor datasheet is a local file, so no network is involved.
    assert main([*argv, "--models", "3d", "--datasheets"], environ) == 0

    assert (demo / "libs/3d/DFN-6.wrl").is_file()
    assert (demo / "libs/docs/sensor.pdf").is_file()


def test_dry_run_prints_plan_and_writes_nothing(
    demo: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    before = snapshot(demo)
    argv = ["--from", "PCM_ACME", "--to", "Local", "--project", str(demo), "--update-project"]

    assert main([*argv, "--dry-run"], environ) == 0

    out = capsys.readouterr().out.splitlines()
    assert "relink     demo.kicad_sch  (11 references)" in out
    assert out[-1] == "Dry run: nothing written."
    assert snapshot(demo) == before


def test_says_nothing_to_do_on_second_run(
    demo: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--from", "PCM_ACME", "--to", "Local", "--project", str(demo), "--update-project"]
    main(argv, environ)
    capsys.readouterr()
    backups = list((demo / "demo-backups").iterdir())

    assert main(argv, environ) == 0

    assert capsys.readouterr().out == "Nothing to do.\n"
    assert list((demo / "demo-backups").iterdir()) == backups


def test_prints_every_error_to_stderr(
    demo: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["-s", "Nowhere:X", "-f", "Nowhere:Y", "--to", "Local", "--project", str(demo)]

    assert main(argv, environ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "error: symbol Nowhere:X not found: library Nowhere not found\n"
        "error: footprint Nowhere:Y not found: library Nowhere not found\n"
    )


def lock_project(demo: Path) -> None:
    (demo / "~demo.kicad_sch.lck").write_text("{}")


def change_existing_model(demo: Path) -> None:
    (demo / "libs/Local.3dshapes/SOIC-8.wrl").write_text("someone else's model")


def break_library(demo: Path) -> None:
    (demo / "libs/Local.kicad_sym").write_text("(kicad_symbol_lib")


def leave_project_as_is(demo: Path) -> None:
    pass


@pytest.mark.parametrize(
    ("prepare", "argv", "message"),
    [
        (lock_project, ["--from", "PCM_ACME", "--update-project"], "close KiCad first"),
        (change_existing_model, ["--from", "PCM_ACME"], "already exists with other content"),
        (break_library, ["--from", "PCM_ACME"], "Local.kicad_sym: unexpected end"),
        (leave_project_as_is, ["-sf", "PCM_ACME_Regulator:Nope"], "not found"),
    ],
    ids=["locked", "model-clash", "broken-library", "missing"],
)
def test_exits_with_1_and_writes_nothing_on_error(
    demo: Path,
    environ: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    prepare: Callable[[Path], None],
    argv: list[str],
    message: str,
) -> None:
    prepare(demo)
    before = snapshot(demo)
    target = [] if "--to" in argv else ["--to", "Local"]

    assert main([*argv, *target, "--project", str(demo)], environ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert snapshot(demo) == before


def test_reads_process_environment_by_default(
    demo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in stock_environ(DEMO_KICAD, tmp_path).items():
        monkeypatch.setenv(name, value)

    assert main(["-s", "Local:Existing", "--to", "Local", "--project", str(demo)]) == 0

    assert (
        capsys.readouterr().out == "skip       Local:Existing  already in Local\nNothing to do.\n"
    )


def test_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out == f"kiadopt {version('kiadopt')}\n"


def test_runs_as_python_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "kiadopt", "--help"], capture_output=True, text=True, check=True
    )

    assert result.stdout.startswith("usage: kiadopt")
