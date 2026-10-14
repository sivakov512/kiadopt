from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from kiadopt import sexpr
from kiadopt.document import Document, read_document
from kiadopt.errors import AdoptError
from kiadopt.libtable import Tables
from kiadopt.project import Project
from kiadopt.symbols import (
    SymbolLib,
    block_field,
    cached_symbol,
    footprint_field,
    read_symbol_lib,
    with_parents,
)
from kiadopt.target import matches_prefix


@dataclass
class Symbol:
    sources: set[str]
    name: str
    block: str
    # Header of the source library; None for a symbol taken from a schematic.
    header: str | None
    users: set[str] = field(default_factory=set)


@dataclass
class Footprint:
    sources: set[str]
    name: str
    document: Document
    users: set[str] = field(default_factory=set)


@dataclass
class Parts:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    footprints: dict[str, Footprint] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Wanted:
    symbol_footprints: Sequence[str]
    symbols: Sequence[str]
    footprints: Sequence[str]
    prefixes: Sequence[str]


def gather_parts(
    wanted: Wanted, project: Project, symbol_tables: Tables, footprint_tables: Tables, target: str
) -> Parts:
    """Symbols with their parents and footprints, keyed by the name they get in the target."""
    gatherer = _Gatherer(wanted, project, symbol_tables, footprint_tables, target)
    gatherer.gather_footprints(gatherer.gather_symbols())
    return gatherer.parts


class _Gatherer:
    def __init__(
        self,
        wanted: Wanted,
        project: Project,
        symbol_tables: Tables,
        footprint_tables: Tables,
        target: str,
    ) -> None:
        self.wanted = wanted
        self.project = project
        self.symbol_tables = symbol_tables
        self.footprint_tables = footprint_tables
        self.target = target
        self.parts = Parts()
        self.libraries: dict[Path, SymbolLib | None] = {}

    def gather_symbols(self) -> set[str]:
        """Returns the footprints to adopt, including those that come with symbols."""
        symbols_in_use, footprints = self._used_from_prefixes()
        footprints |= set(self.wanted.footprints)
        explicit = set(self.wanted.symbol_footprints) | set(self.wanted.symbols)
        for lib_id in sorted(explicit | symbols_in_use):
            # A symbol that only --from asked for may come from the schematic cache.
            footprint = self._gather_symbol(lib_id, from_cache=lib_id not in explicit)
            if lib_id in self.wanted.symbol_footprints:
                if footprint:
                    footprints.add(footprint)
                elif footprint is not None:
                    self.parts.errors.append(f"symbol {lib_id} has an empty Footprint field")
            elif lib_id in symbols_in_use and footprint and self._from_prefix(footprint):
                footprints.add(footprint)
        return footprints

    def _gather_symbol(self, lib_id: str, *, from_cache: bool) -> str | None:
        """Returns the Footprint field of the symbol, None when the symbol is not found."""
        nickname, _, name = lib_id.partition(":")
        path = self._find(self.symbol_tables, nickname)
        library = self._symbol_lib(path) if path is not None else None
        if library is None or name not in library.blocks:
            if from_cache:
                return self._gather_cached_symbol(lib_id, name)
            where = f"not in {path}" if library is not None else f"library {nickname} not found"
            self.parts.errors.append(f"symbol {lib_id} not found: {where}")
            return None
        chain = with_parents(library, name)
        for index, member in enumerate(chain):
            users = {chain[index - 1]} if index else set()
            block = library.blocks[member]
            self._add_symbol(Symbol({f"{nickname}:{member}"}, member, block, library.header, users))
        return footprint_field(library, name)

    def _gather_cached_symbol(self, lib_id: str, name: str) -> str | None:
        block = cached_symbol(self.project.sheets, lib_id, name)
        if block is None:
            self.parts.errors.append(f"symbol {lib_id} not found in its library or the schematic")
            return None
        self.parts.warnings.append(
            f"symbol {lib_id} not found in its library; copied from the schematic"
        )
        self._add_symbol(Symbol({lib_id}, name, block, None))
        return block_field(block, "Footprint") or ""

    def _add_symbol(self, symbol: Symbol) -> None:
        known = self.parts.symbols.get(symbol.name)
        if known is None:
            self.parts.symbols[symbol.name] = symbol
        elif known.sources == symbol.sources or sexpr.equivalent(known.block, symbol.block):
            known.sources |= symbol.sources
            known.users |= symbol.users
        else:
            self._name_clash("symbol", known.sources | symbol.sources, symbol.name)

    def gather_footprints(self, wanted: set[str]) -> None:
        for lib_id in sorted(wanted):
            nickname, _, name = lib_id.partition(":")
            library = self._find(self.footprint_tables, nickname)
            path = library / f"{name}.kicad_mod" if library is not None else None
            if path is None or not path.is_file():
                where = f"no {path}" if path is not None else f"library {nickname} not found"
                self.parts.errors.append(f"footprint {lib_id} not found: {where}")
                continue
            footprint = Footprint({lib_id}, name, read_document(path))
            known = self.parts.footprints.get(name)
            if known is None:
                self.parts.footprints[name] = footprint
            elif sexpr.equivalent(known.document.text, footprint.document.text):
                known.sources |= footprint.sources
            else:
                self._name_clash("footprint", known.sources | footprint.sources, name)
        for symbol in self.parts.symbols.values():
            field_value = block_field(symbol.block, "Footprint")
            for footprint in self.parts.footprints.values():
                if field_value in footprint.sources:
                    footprint.users.add(symbol.name)

    def _name_clash(self, kind: str, sources: set[str], name: str) -> None:
        listed = " and ".join(sorted(sources))
        self.parts.errors.append(f"{kind}s {listed} differ but both map to {self.target}:{name}")

    def _find(self, tables: Tables, nickname: str) -> Path | None:
        try:
            return tables.find(nickname)
        except AdoptError as exc:
            self.parts.errors.extend(exc.messages)
            return None

    def _symbol_lib(self, path: Path) -> SymbolLib | None:
        if path not in self.libraries:
            self.libraries[path] = read_symbol_lib(path) if path.exists() else None
        return self.libraries[path]

    def _used_from_prefixes(self) -> tuple[set[str], set[str]]:
        symbols: set[str] = set()
        footprints: set[str] = set()
        if not self.wanted.prefixes:
            return symbols, footprints
        for sheet in self.project.sheets:
            for placed in sheet.root.children("symbol"):
                lib_id = placed.value("lib_id")
                if lib_id is not None and self._from_prefix(lib_id.value):
                    symbols.add(lib_id.value)
                field = placed.property("Footprint")
                if field is not None and self._from_prefix(field.value):
                    footprints.add(field.value)
        board = self.project.board
        for footprint in board.root.children("footprint") if board is not None else ():
            footprint_id = footprint.atom(1)
            if footprint_id is not None and self._from_prefix(footprint_id.value):
                footprints.add(footprint_id.value)
        return symbols, footprints

    def _from_prefix(self, lib_id: str) -> bool:
        return any(matches_prefix(lib_id, prefix) for prefix in self.wanted.prefixes)
