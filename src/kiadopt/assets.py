from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from kiadopt.env import project_reference, resolve_path

Fetch = Callable[[str], bytes]
# A reference as written in a part, and the name of that part.
Use = tuple[str, str]

MODEL = "3D model"
DATASHEET = "datasheet"

_URL = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class Asset:
    kind: str
    source: str
    dest: Path
    reference: str
    content: Path | bytes
    exists: bool
    users: set[str] = field(default_factory=set)

    def data(self) -> bytes:
        return self.content if isinstance(self.content, bytes) else self.content.read_bytes()


@dataclass
class Assets:
    items: list[Asset] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Placement:
    folder: Path
    project_dir: Path
    variables: Mapping[str, str]


def collect_models(uses: Iterable[Use], placement: Placement) -> Assets:
    result = Assets()
    by_source: dict[Path, Asset] = {}
    for raw, user in sorted(set(uses)):
        if raw.startswith("kicad-embed://"):
            continue
        path = resolve_path(raw, placement.variables, placement.project_dir)
        if path.is_relative_to(placement.project_dir) or path.is_relative_to(placement.folder):
            continue
        if not path.is_file():
            result.warnings.append(f"3D model not found, path kept: {raw} ({user})")
            continue
        asset = by_source.get(path)
        if asset is None:
            asset = _place(result, MODEL, raw, path, path.name, placement)
            if asset is None:
                continue
            by_source[path] = asset
        asset.users.add(user)
        result.references[raw] = asset.reference
    return result


def collect_datasheets(uses: Iterable[Use], placement: Placement, fetch: Fetch) -> Assets:
    # A datasheet that cannot be saved is a warning: the part keeps its link.
    result = Assets()
    by_source: dict[str, Asset | None] = {}
    for value, user in sorted(set(uses)):
        if value in ("", "~"):
            continue
        if value not in by_source:
            by_source[value] = _datasheet(result, value, user, placement, fetch)
        asset = by_source[value]
        if asset is not None:
            asset.users.add(user)
            result.references[value] = asset.reference
    return result


def _datasheet(
    result: Assets, value: str, user: str, placement: Placement, fetch: Fetch
) -> Asset | None:
    if _URL.match(value):
        try:
            data = fetch(value)
        except OSError as exc:
            result.warnings.append(f"datasheet download failed, link kept: {value}: {exc}")
            return None
        if not data.startswith(b"%PDF-"):
            result.warnings.append(f"datasheet is not a PDF, link kept: {value}")
            return None
        return _place(result, DATASHEET, value, data, _url_file_name(value), placement)
    path = resolve_path(value, placement.variables, placement.project_dir)
    if path.is_relative_to(placement.project_dir):
        return None
    if not path.is_file():
        result.warnings.append(f"datasheet not found, link kept: {value} ({user})")
        return None
    return _place(result, DATASHEET, value, path, path.name, placement)


def _url_file_name(url: str) -> str:
    name = unquote(PurePosixPath(urlparse(url).path).name) or "datasheet"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def _place(
    result: Assets,
    kind: str,
    source: str,
    content: Path | bytes,
    name: str,
    placement: Placement,
) -> Asset | None:
    dest = placement.folder / name
    data = content if isinstance(content, bytes) else content.read_bytes()
    taken = next((other for other in result.items if other.dest == dest), None)
    if taken is not None:
        if taken.data() == data:
            return taken
        conflict = f"{taken.source} and {source} both map to {dest}"
    elif dest.exists() and dest.read_bytes() != data:
        conflict = f"{dest} already exists with other content ({source})"
    else:
        reference = project_reference(dest, placement.project_dir)
        asset = Asset(kind, source, dest, reference, content, exists=dest.exists())
        result.items.append(asset)
        return asset
    if kind == MODEL:
        result.errors.append(f"3D model conflict: {conflict}")
    else:
        result.warnings.append(f"datasheet name clash, link kept: {conflict}")
    return None
