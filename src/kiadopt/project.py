from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kiadopt.document import Document, read_document
from kiadopt.errors import AdoptError


@dataclass(frozen=True)
class Project:
    dir: Path
    name: str
    sheets: tuple[Document, ...]
    board: Document | None


def load_project(path: Path) -> Project:
    pro = path if path.suffix == ".kicad_pro" else _single_project_file(path)
    if not pro.is_file():
        raise AdoptError(f"project file not found: {pro}")
    directory = pro.parent
    root_sheet = directory / f"{pro.stem}.kicad_sch"
    board_file = directory / f"{pro.stem}.kicad_pcb"
    sheets = _load_hierarchy(root_sheet) if root_sheet.is_file() else ()
    board = read_document(board_file) if board_file.is_file() else None
    return Project(directory, pro.stem, sheets, board)


def _single_project_file(directory: Path) -> Path:
    found = sorted(directory.glob("*.kicad_pro"))
    if len(found) != 1:
        raise AdoptError(f"expected exactly one .kicad_pro in {directory}, found {len(found)}")
    return found[0]


def _load_hierarchy(root: Path) -> tuple[Document, ...]:
    loaded: dict[Path, Document] = {}
    pending = [root]
    while pending:
        path = pending.pop(0)
        if path in loaded:
            continue
        if not path.is_file():
            raise AdoptError(f"sheet file not found: {path}")
        document = read_document(path)
        loaded[path] = document
        # Sheet file names are relative to the parent sheet.
        pending += [path.parent / name for name in sheet_files(document)]
    return tuple(loaded.values())


def sheet_files(document: Document) -> list[str]:
    files = []
    for sheet in document.root.children("sheet"):
        name = sheet.property("Sheetfile")
        if name is not None:
            files.append(name.value)
    return files


def lock_files(project: Project) -> list[Path]:
    directories = {project.dir} | {sheet.path.parent for sheet in project.sheets}
    return sorted(lock for directory in directories for lock in directory.glob("~*.lck"))
