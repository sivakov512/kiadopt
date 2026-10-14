from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from kiadopt import sexpr
from kiadopt.assets import Assets, Fetch, Placement, Use, collect_datasheets, collect_models
from kiadopt.env import KicadEnv, display_path, project_reference
from kiadopt.errors import AdoptError
from kiadopt.libtable import FOOTPRINTS, SYMBOLS, add_entry, load_tables, new_table
from kiadopt.parts import Parts, Wanted, gather_parts
from kiadopt.project import Project, load_project, lock_files
from kiadopt.relink import (
    PDF_URL,
    Relink,
    board_text,
    footprint_edits,
    schematic_text,
    symbol_edits,
)
from kiadopt.symbols import (
    DEFAULT_HEADER,
    block_field,
    edit_block,
    library_text,
    order_parents_first,
    read_symbol_lib,
)
from kiadopt.target import Target, resolve_target

REPORT_ORDER = ("symbol", "footprint", "3D model", "datasheet", "register", "relink", "skip")


@dataclass(frozen=True)
class Request:
    project: Path
    target: str
    symbol_footprints: Sequence[str] = ()
    symbols: Sequence[str] = ()
    footprints: Sequence[str] = ()
    prefixes: Sequence[str] = ()
    lib_dir: Path | None = None
    models_dir: Path | None = None
    datasheets_dir: Path | None = None
    update_project: bool = False


@dataclass(frozen=True)
class Action:
    kind: str
    subject: str
    target: str = ""
    users: tuple[str, ...] = ()
    detail: str = ""


@dataclass
class Plan:
    project: Project
    actions: list[Action]
    warnings: list[str]
    copies: dict[Path, Path]
    blobs: dict[Path, bytes]
    texts: dict[Path, str]

    @property
    def has_changes(self) -> bool:
        return bool(self.copies or self.blobs or self.texts)


def plan(request: Request, env: KicadEnv, fetch: Fetch) -> Plan:
    """Work out what to copy and rewrite. Raises AdoptError with every problem found."""
    wanted = Wanted(
        request.symbol_footprints, request.symbols, request.footprints, request.prefixes
    )
    if not (wanted.symbol_footprints or wanted.symbols or wanted.footprints or wanted.prefixes):
        raise AdoptError("nothing to adopt: give -sf, -s, -f or --from")
    project = load_project(request.project.absolute())
    if request.update_project:
        locks = lock_files(project)
        if locks:
            names = ", ".join(display_path(lock, project.dir) for lock in locks)
            raise AdoptError(f"the project is open in KiCad ({names}); close KiCad first")
    symbol_tables = load_tables(SYMBOLS, env, project.dir)
    footprint_tables = load_tables(FOOTPRINTS, env, project.dir)
    target = resolve_target(
        request.target,
        project.dir,
        symbol_tables,
        footprint_tables,
        prefixes=request.prefixes,
        lib_dir=request.lib_dir,
        models_dir=request.models_dir,
    )
    parts = gather_parts(wanted, project, symbol_tables, footprint_tables, target.name)
    if parts.errors:
        raise AdoptError(*parts.errors)
    return _Writer(request, env, fetch, project, target, parts).build()


class _Writer:
    """Turns the gathered parts into files to write and references to rewrite."""

    def __init__(
        self,
        request: Request,
        env: KicadEnv,
        fetch: Fetch,
        project: Project,
        target: Target,
        parts: Parts,
    ) -> None:
        self.request = request
        self.env = env
        self.fetch = fetch
        self.project = project
        self.target = target
        self.symbols = parts.symbols
        self.footprints = parts.footprints
        self.errors: list[str] = []
        self.warnings = list(parts.warnings)
        self.actions: dict[str, list[Action]] = {kind: [] for kind in REPORT_ORDER}
        self.copies: dict[Path, Path] = {}
        self.blobs: dict[Path, bytes] = {}
        self.texts: dict[Path, str] = {}

    def build(self) -> Plan:
        relink = self._build_relink()
        self._write_symbols(relink)
        self._write_footprints(relink)
        self._register()
        if self.request.update_project:
            self._relink_project(relink)
        if self.errors:
            raise AdoptError(*self.errors)
        actions = [action for group in self.actions.values() for action in group]
        return Plan(self.project, actions, self.warnings, self.copies, self.blobs, self.texts)

    def _build_relink(self) -> Relink:
        target = self.target.name
        symbol_ids = {
            source: f"{target}:{symbol.name}"
            for symbol in self.symbols.values()
            for source in symbol.sources
        }
        footprint_ids = {
            source: f"{target}:{footprint.name}"
            for footprint in self.footprints.values()
            for source in footprint.sources
        }
        models = collect_models(
            self._model_uses(footprint_ids),
            Placement(self.target.models_dir, self.project.dir, self.env.variables),
        )
        self._take_assets(models)
        datasheets = Assets()
        if self.request.datasheets_dir is not None:
            folder = self.request.datasheets_dir.absolute()
            placement = Placement(folder, self.project.dir, self.env.variables)
            datasheets = collect_datasheets(self._datasheet_uses(), placement, self.fetch)
            self._take_assets(datasheets)
        return Relink(target, symbol_ids, footprint_ids, models.references, datasheets.references)

    def _model_uses(self, footprint_ids: dict[str, str]) -> Iterator[Use]:
        for footprint in self.footprints.values():
            for path in _model_paths(footprint.document.root):
                yield path, footprint.name
        board = self.project.board
        if not self.request.update_project or board is None:
            return
        # The board may carry models the library footprint does not have.
        for placed in board.root.children("footprint"):
            footprint_id = placed.atom(1)
            if footprint_id is not None and footprint_id.value in footprint_ids:
                for path in _model_paths(placed):
                    yield path, footprint_id.value.partition(":")[2]

    def _datasheet_uses(self) -> Iterator[Use]:
        for symbol in self.symbols.values():
            datasheet = block_field(symbol.block, "Datasheet")
            if datasheet is not None:
                yield datasheet, symbol.name
        for footprint in self.footprints.values():
            root = footprint.document.root
            field = root.property("Datasheet")
            if field is not None:
                yield field.value, footprint.name
            descr = root.value("descr")
            for url in PDF_URL.findall(descr.value) if descr is not None else ():
                yield url, footprint.name

    def _take_assets(self, assets: Assets) -> None:
        self.errors += assets.errors
        self.warnings += assets.warnings
        for asset in sorted(assets.items, key=lambda item: item.source):
            dest = self._display(asset.dest)
            if asset.exists:
                self.actions["skip"].append(Action("skip", dest, detail="already exists"))
                continue
            users = tuple(sorted(asset.users))
            self.actions[asset.kind].append(Action(asset.kind, asset.source, dest, users))
            if isinstance(asset.content, bytes):
                self.blobs[asset.dest] = asset.content
            else:
                self.copies[asset.dest] = asset.content

    def _write_symbols(self, relink: Relink) -> None:
        if not self.symbols:
            return
        path = self.target.symbol_lib
        existing = read_symbol_lib(path) if path.exists() else None
        blocks = {name: symbol.block for name, symbol in self.symbols.items()}
        new_blocks = []
        for name in order_parents_first(blocks):
            symbol = self.symbols[name]
            block = edit_block(symbol.block, lambda node: symbol_edits(node, relink))
            if existing is not None and name in existing.blocks:
                self._skip(f"{self.target.name}:{name}", block, existing.blocks[name])
                continue
            new_blocks.append(block)
            users = tuple(sorted(symbol.users))
            source = min(symbol.sources)
            self.actions["symbol"].append(Action("symbol", source, self._display(path), users))
        if new_blocks:
            headers = (symbol.header for symbol in self.symbols.values() if symbol.header)
            text = path.read_bytes().decode("utf-8") if existing is not None else None
            self.texts[path] = library_text(text, next(headers, DEFAULT_HEADER), new_blocks)

    def _write_footprints(self, relink: Relink) -> None:
        for name in sorted(self.footprints):
            footprint = self.footprints[name]
            document = footprint.document
            text = sexpr.replace_values(document.text, footprint_edits(document.root, relink))
            dest = self.target.footprint_lib / f"{name}.kicad_mod"
            if dest.exists():
                self._skip(f"{self.target.name}:{name}", text, dest.read_bytes().decode("utf-8"))
                continue
            self.texts[dest] = text
            users = tuple(sorted(footprint.users))
            source = min(footprint.sources)
            self.actions["footprint"].append(
                Action("footprint", source, self._display(dest), users)
            )

    def _skip(self, lib_id: str, ours: str, theirs: str) -> None:
        self.actions["skip"].append(Action("skip", lib_id, detail=f"already in {self.target.name}"))
        if not sexpr.equivalent(ours, theirs):
            self.warnings.append(f"{lib_id} differs from the adopted part; kept the existing one")

    def _register(self) -> None:
        target = self.target
        for kind, adopted, registered, path in (
            (SYMBOLS, self.symbols, target.symbol_registered, target.symbol_lib),
            (FOOTPRINTS, self.footprints, target.footprint_registered, target.footprint_lib),
        ):
            if not adopted or registered:
                continue
            table = self.project.dir / kind.table
            text = table.read_bytes().decode("utf-8") if table.exists() else new_table(kind)
            uri = project_reference(path, self.project.dir)
            self.texts[table] = add_entry(text, target.name, uri)
            self.actions["register"].append(Action("register", target.name, kind.table))

    def _relink_project(self, relink: Relink) -> None:
        changes = [(*schematic_text(sheet, relink), sheet.path) for sheet in self.project.sheets]
        if self.project.board is not None:
            changes.append((*board_text(self.project.board, relink), self.project.board.path))
        for text, count, path in changes:
            if count:
                self.texts[path] = text
                noun = "reference" if count == 1 else "references"
                detail = f"({count} {noun})"
                self.actions["relink"].append(Action("relink", self._display(path), detail=detail))

    def _display(self, path: Path) -> str:
        return display_path(path, self.project.dir)


def _model_paths(footprint: sexpr.Node) -> Iterator[str]:
    for node in sexpr.walk(footprint):
        path = node.atom(1) if node.head == "model" else None
        if path is not None:
            yield path.value
