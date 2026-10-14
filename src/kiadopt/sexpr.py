# Nodes and atoms keep their offsets in the source text, so a value can be
# replaced in place without reformatting the rest of the file.

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.DOTALL)
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_UNESCAPED = {"n": "\n", "r": "\r", "t": "\t"}
_ESCAPED = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r"}


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Atom:
    value: str
    start: int
    end: int


@dataclass
class Node:
    start: int
    end: int = -1
    items: list[Node | Atom] = field(default_factory=list)

    @property
    def head(self) -> str:
        first = self.items[0] if self.items else None
        return first.value if isinstance(first, Atom) else ""

    def atom(self, index: int) -> Atom | None:
        item = self.items[index] if index < len(self.items) else None
        return item if isinstance(item, Atom) else None

    def children(self, head: str) -> Iterator[Node]:
        return (item for item in self.items if isinstance(item, Node) and item.head == head)

    def child(self, head: str) -> Node | None:
        return next(self.children(head), None)

    def value(self, head: str) -> Atom | None:
        node = self.child(head)
        return node.atom(1) if node is not None else None

    def property(self, name: str) -> Atom | None:
        for prop in self.children("property"):
            key = prop.atom(1)
            if key is not None and key.value == name:
                return prop.atom(2)
        return None


def parse(text: str) -> Node:
    stack: list[Node] = []
    root: Node | None = None
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN.match(text, pos)
        if match is None:
            if text[pos:].strip():
                raise ParseError(f"unexpected character at offset {pos}")
            break
        pos = match.end()
        opening, closing, string, bare = match.groups()
        if opening:
            if root is not None and not stack:
                raise ParseError(f"more than one top-level list at offset {match.start(1)}")
            node = Node(match.start(1))
            if stack:
                stack[-1].items.append(node)
            else:
                root = node
            stack.append(node)
        elif closing:
            if not stack:
                raise ParseError(f"unbalanced ')' at offset {match.start(2)}")
            stack.pop().end = pos
        elif not stack:
            raise ParseError(f"atom outside of a list at offset {match.start()}")
        elif string is not None:
            stack[-1].items.append(Atom(unescape(string), match.start(3) - 1, pos))
        else:
            stack[-1].items.append(Atom(bare, match.start(4), pos))
    if stack or root is None:
        raise ParseError("unexpected end of text")
    return root


def tokens(text: str) -> list[str]:
    result = []
    for match in _TOKEN.finditer(text):
        opening, closing, string, bare = match.groups()
        if string is not None:
            result.append(unescape(string))
        else:
            result.append(opening or closing or bare)
    return result


def equivalent(first: str, second: str) -> bool:
    # KiCad may re-save a file with other formatting; only the tokens matter.
    return tokens(first) == tokens(second)


def walk(node: Node) -> Iterator[Node]:
    yield node
    for item in node.items:
        if isinstance(item, Node):
            yield from walk(item)


def unescape(body: str) -> str:
    return _ESCAPE.sub(lambda m: _UNESCAPED.get(m[1], m[1]), body)


def quote(value: str) -> str:
    return '"' + "".join(_ESCAPED.get(char, char) for char in value) + '"'


def splice(text: str, edits: Iterable[tuple[int, int, str]]) -> str:
    parts = []
    pos = 0
    for start, end, replacement in sorted(edits):
        if start < pos:
            raise ValueError(f"overlapping edits at offset {start}")
        parts += [text[pos:start], replacement]
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


def value_spans(edits: Iterable[tuple[Atom, str]]) -> list[tuple[int, int, str]]:
    return [(atom.start, atom.end, quote(value)) for atom, value in edits]


def replace_values(text: str, edits: Iterable[tuple[Atom, str]]) -> str:
    return splice(text, value_spans(edits))


def line_block(text: str, node: Node) -> str:
    # Includes the indentation before the node, so the block can be pasted as is.
    line_start = text.rfind("\n", 0, node.start) + 1
    return text[line_start : node.end]


def append_lines(text: str, node: Node, lines: str) -> str:
    closing = node.end - 1
    if not text[:closing].endswith("\n"):
        lines = "\n" + lines
    return text[:closing] + lines + text[closing:]
