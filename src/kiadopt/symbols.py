from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from kiadopt import sexpr
from kiadopt.document import Document, read_document
from kiadopt.env import KICAD_VERSION

SYMBOL_LIB_VERSION = 20251024

# For a new library made only of symbols taken from a schematic cache.
DEFAULT_HEADER = (
    f'\t(version {SYMBOL_LIB_VERSION})\n\t(generator "kiadopt")\n'
    f'\t(generator_version "{KICAD_VERSION}")\n'
)


@dataclass(frozen=True)
class SymbolLib:
    header: str
    blocks: dict[str, str]


def read_symbol_lib(path: Path) -> SymbolLib:
    # A library is either one file or a folder of files.
    files = sorted(path.glob("*.kicad_sym")) if path.is_dir() else [path]
    documents = [read_document(file) for file in files]
    blocks = {}
    for document in documents:
        for node in document.root.children("symbol"):
            blocks[_name(node)] = sexpr.line_block(document.text, node)
    header = _header(documents[0]) if documents else DEFAULT_HEADER
    return SymbolLib(header, blocks)


def _header(document: Document) -> str:
    lines = []
    for head in ("version", "generator", "generator_version"):
        node = document.root.child(head)
        if node is not None:
            lines.append("\t" + document.text[node.start : node.end] + "\n")
    return "".join(lines)


def _name(node: sexpr.Node) -> str:
    atom = node.atom(1)
    return atom.value if atom is not None else ""


def _parse_block(block: str) -> sexpr.Node:
    return sexpr.parse(block.lstrip())


def parent_name(block: str) -> str | None:
    atom = _parse_block(block).value("extends")
    return atom.value if atom is not None else None


def block_field(block: str, name: str) -> str | None:
    atom = _parse_block(block).property(name)
    return atom.value if atom is not None else None


def footprint_field(library: SymbolLib, name: str) -> str:
    block = library.blocks[name]
    field = block_field(block, "Footprint")
    if field is not None:
        return field
    parent = parent_name(block)
    return footprint_field(library, parent) if parent in library.blocks else ""


def with_parents(library: SymbolLib, name: str) -> list[str]:
    chain = [name]
    parent = parent_name(library.blocks[name])
    while parent is not None and parent in library.blocks and parent not in chain:
        chain.append(parent)
        parent = parent_name(library.blocks[parent])
    return chain


def cached_symbol(sheets: Iterable[Document], lib_id: str, name: str) -> str | None:
    for sheet in sheets:
        cache = sheet.root.child("lib_symbols")
        for node in cache.children("symbol") if cache is not None else ():
            if _name(node) == lib_id:
                # Cache entries sit one level deeper than library symbols.
                block = _dedent(sexpr.line_block(sheet.text, node))
                return rename(block, name)
    return None


def rename(block: str, name: str) -> str:
    def name_edit(node: sexpr.Node) -> list[tuple[sexpr.Atom, str]]:
        atom = node.atom(1)
        return [(atom, name)] if atom is not None else []

    return edit_block(block, name_edit)


def edit_block(block: str, edits: Callable[[sexpr.Node], list[tuple[sexpr.Atom, str]]]) -> str:
    indent = len(block) - len(block.lstrip())
    body = block[indent:]
    return block[:indent] + sexpr.replace_values(body, edits(sexpr.parse(body)))


def _dedent(block: str) -> str:
    return "\n".join(line.removeprefix("\t") for line in block.split("\n"))


def order_parents_first(blocks: dict[str, str]) -> list[str]:
    # KiCad needs a parent to come before the symbols that extend it.
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        parent = parent_name(blocks[name])
        if parent in blocks:
            visit(parent)
        ordered.append(name)

    for name in sorted(blocks):
        visit(name)
    return ordered


def library_text(existing: str | None, header: str, blocks: list[str]) -> str:
    lines = "".join(block + "\n" for block in blocks)
    if existing is None:
        return f"(kicad_symbol_lib\n{header}{lines})\n"
    return sexpr.append_lines(existing, sexpr.parse(existing), lines)
