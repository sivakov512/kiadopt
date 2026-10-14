from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kiadopt import sexpr
from kiadopt.errors import AdoptError


@dataclass(frozen=True)
class Document:
    path: Path
    text: str
    root: sexpr.Node


def read_document(path: Path) -> Document:
    # read_text() would translate CRLF and break byte-exact edits.
    text = path.read_bytes().decode("utf-8")
    return parse_document(path, text)


def parse_document(path: Path, text: str) -> Document:
    try:
        return Document(path, text, sexpr.parse(text))
    except sexpr.ParseError as exc:
        raise AdoptError(f"{path}: {exc}") from exc
