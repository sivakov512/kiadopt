from pathlib import Path

import pytest

from kiadopt.errors import AdoptError
from kiadopt.project import load_project, lock_files


def test_loads_sheets_board_and_name(mini: Path) -> None:
    project = load_project(mini)

    assert project.name == "mini"
    assert [sheet.path.name for sheet in project.sheets] == ["mini.kicad_sch", "sub.kicad_sch"]
    assert project.board is not None
    assert project.board.path.name == "mini.kicad_pcb"


def test_accepts_project_file_instead_of_folder(mini: Path) -> None:
    assert load_project(mini / "mini.kicad_pro").dir == mini


def test_loads_sheet_used_twice_once(demo: Path) -> None:
    project = load_project(demo)

    assert [sheet.path.name for sheet in project.sheets] == ["demo.kicad_sch", "channel.kicad_sch"]


def test_raises_without_project_file(tmp_path: Path) -> None:
    with pytest.raises(AdoptError, match="exactly one"):
        load_project(tmp_path)


def test_raises_with_two_project_files(mini: Path) -> None:
    (mini / "other.kicad_pro").write_text("{}")

    with pytest.raises(AdoptError, match="found 2"):
        load_project(mini)


def test_raises_if_given_project_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(AdoptError, match="not found"):
        load_project(tmp_path / "x.kicad_pro")


def test_raises_if_sheet_file_is_missing(mini: Path) -> None:
    (mini / "sub.kicad_sch").unlink()

    with pytest.raises(AdoptError, match="sheet file not found"):
        load_project(mini)


def test_names_broken_schematic(mini: Path) -> None:
    (mini / "sub.kicad_sch").write_text("(kicad_sch")

    with pytest.raises(AdoptError, match=r"sub\.kicad_sch: unexpected end"):
        load_project(mini)


def test_loads_project_without_schematic_and_board(tmp_path: Path) -> None:
    (tmp_path / "bare.kicad_pro").write_text("{}")

    project = load_project(tmp_path)

    assert project.sheets == ()
    assert project.board is None


def test_finds_kicad_lock_files(mini: Path) -> None:
    project = load_project(mini)
    assert lock_files(project) == []

    (mini / "~mini.kicad_sch.lck").write_text("")

    assert [lock.name for lock in lock_files(project)] == ["~mini.kicad_sch.lck"]
