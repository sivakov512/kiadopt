from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from kiadopt import sexpr
from kiadopt.document import Document

PDF_URL = re.compile(r"https?://\S+?\.pdf(?=[.,;:)]*(?:\s|$))", re.IGNORECASE)

Edit = tuple[sexpr.Atom, str]


@dataclass(frozen=True)
class Relink:
    target: str
    symbols: Mapping[str, str]
    footprints: Mapping[str, str]
    models: Mapping[str, str]
    datasheets: Mapping[str, str]

    def footprint_filters(self, filters: str) -> str:
        libraries = {footprint.partition(":")[0] for footprint in self.footprints}

        def pattern(match: re.Match[str]) -> str:
            nickname, colon, rest = match[0].partition(":")
            return f"{self.target}:{rest}" if colon and nickname in libraries else match[0]

        return re.sub(r"\S+", pattern, filters)


def _rewrite(atom: sexpr.Atom | None, change: Callable[[str], str]) -> list[Edit]:
    if atom is None:
        return []
    value = change(atom.value)
    return [(atom, value)] if value != atom.value else []


def _lookup(atom: sexpr.Atom | None, mapping: Mapping[str, str]) -> list[Edit]:
    return _rewrite(atom, lambda value: mapping.get(value, value))


def symbol_edits(symbol: sexpr.Node, relink: Relink) -> list[Edit]:
    return [
        *_lookup(symbol.property("Footprint"), relink.footprints),
        *_lookup(symbol.property("Datasheet"), relink.datasheets),
        *_rewrite(symbol.property("ki_fp_filters"), relink.footprint_filters),
    ]


def footprint_edits(footprint: sexpr.Node, relink: Relink) -> list[Edit]:
    edits = []
    for node in sexpr.walk(footprint):
        if node.head == "model":
            edits += _lookup(node.atom(1), relink.models)
    edits += _lookup(footprint.property("Datasheet"), relink.datasheets)
    edits += _rewrite(
        footprint.value("descr"),
        lambda value: PDF_URL.sub(lambda m: relink.datasheets.get(m[0], m[0]), value),
    )
    return edits


def schematic_text(sheet: Document, relink: Relink) -> tuple[str, int]:
    edits: list[Edit] = []
    for symbol in sheet.root.children("symbol"):
        lib_id = symbol.value("lib_id")
        if lib_id is not None and lib_id.value in relink.symbols:
            edits += _lookup(lib_id, relink.symbols)
            edits += symbol_edits(symbol, relink)
        else:
            # Any placed symbol may use an adopted footprint.
            edits += _lookup(symbol.property("Footprint"), relink.footprints)
    cache_edits, removals = _cache_edits(sheet, relink)
    edits += cache_edits
    text = sexpr.splice(sheet.text, sexpr.value_spans(edits) + removals)
    return text, len(edits) + len(removals)


def _cache_edits(sheet: Document, relink: Relink) -> tuple[list[Edit], list[tuple[int, int, str]]]:
    # The cached copy must match the library symbol, or ERC reports a mismatch.
    # When the new name is cached already, the old copy is dropped.
    cache = sheet.root.child("lib_symbols")
    if cache is None:
        return [], []
    entries = [(node, node.atom(1)) for node in cache.children("symbol")]
    taken = {atom.value for _, atom in entries if atom is not None} - set(relink.symbols)
    edits: list[Edit] = []
    removals = []
    for node, atom in entries:
        if atom is None or atom.value not in relink.symbols:
            continue
        new_name = relink.symbols[atom.value]
        if new_name in taken:
            removals.append(_line_span(sheet.text, node))
            continue
        taken.add(new_name)
        edits += _lookup(atom, relink.symbols)
        edits += symbol_edits(node, relink)
    return edits, removals


def _line_span(text: str, node: sexpr.Node) -> tuple[int, int, str]:
    start = text.rfind("\n", 0, node.start) + 1
    end = node.end + 1 if text.startswith("\n", node.end) else node.end
    return start, end, ""


def board_text(board: Document, relink: Relink) -> tuple[str, int]:
    edits: list[Edit] = []
    for footprint in board.root.children("footprint"):
        footprint_id = footprint.atom(1)
        if footprint_id is not None and footprint_id.value in relink.footprints:
            edits += _lookup(footprint_id, relink.footprints)
            edits += footprint_edits(footprint, relink)
    return sexpr.replace_values(board.text, edits), len(edits)
