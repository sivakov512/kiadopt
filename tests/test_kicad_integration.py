# Checks with KiCad itself: ERC, DRC and a 3D render of the board. Run with
# `pytest -m kicad`; skipped when kicad-cli is not installed.

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

import pytest

from kiadopt import Request, apply, load_env, plan
from tests.helpers import DEMO_KICAD, FIXTURES, FakeWeb, stock_environ

pytestmark = [
    pytest.mark.kicad,
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not found"),
]

LIBRARY_PROBLEMS = {
    "lib_symbol_issues",
    "lib_symbol_mismatch",
    "footprint_link_issues",
    "lib_footprint_issues",
    "lib_footprint_mismatch",
}


class Kicad:
    def __init__(self, root: Path) -> None:
        # kicad-cli rewrites kicad_common.json on every run, so it gets a copy.
        self.config = root / "config"
        shutil.copytree(DEMO_KICAD / "config", self.config)
        self.empty = root / "no-packages"
        self.empty.mkdir()
        self.root = root

    def run(self, *arguments: str, packages: bool) -> None:
        environ = {
            **os.environ,
            **stock_environ(DEMO_KICAD, self.root / "home"),
            "KICAD_CONFIG_HOME": str(self.config),
        }
        if not packages:
            environ["KICAD10_3RD_PARTY"] = str(self.empty)
        subprocess.run(
            ["nice", "kicad-cli", *arguments], env=environ, check=True, capture_output=True
        )

    def problems(self, project: Path, *, packages: bool) -> dict[str, list[str]]:
        erc, drc = self.root / "erc.json", self.root / "drc.json"
        sheet, board = str(project / "demo.kicad_sch"), str(project / "demo.kicad_pcb")
        self.run(
            "sch",
            "erc",
            "--format",
            "json",
            "--severity-all",
            "-o",
            str(erc),
            sheet,
            packages=packages,
        )
        self.run(
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "-o",
            str(drc),
            board,
            packages=packages,
        )
        violations = [v for s in json.loads(erc.read_text())["sheets"] for v in s["violations"]]
        violations += json.loads(drc.read_text())["violations"]
        found: dict[str, list[str]] = {}
        for violation in violations:
            if violation["type"] in LIBRARY_PROBLEMS:
                items = [item["description"] for item in violation["items"]]
                found.setdefault(violation["type"], []).extend(items)
        return found

    def render(self, project: Path, name: str, *, packages: bool) -> list[bytes]:
        image = self.root / f"{name}.png"
        board = str(project / "demo.kicad_pcb")
        self.run(
            "pcb", "render", "-w", "480", "-h", "320", "-o", str(image), board, packages=packages
        )
        return png_rows(image.read_bytes())


def png_rows(data: bytes) -> list[bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    position, compressed = 8, b""
    width = height = channels = 0
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            assert depth == 8
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
        elif kind == b"IDAT":
            compressed += body
        position += 12 + length
    raw = zlib.decompress(compressed)
    stride = width * channels
    rows: list[bytes] = []
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        line_filter = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        for x in range(stride):
            left = line[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            line[x] = (line[x] + _predict(line_filter, left, up, corner)) & 0xFF
        rows.append(bytes(line))
        previous = line
    return rows


def _predict(kind: int, left: int, up: int, corner: int) -> int:
    if kind == 0:
        return 0
    if kind == 1:
        return left
    if kind == 2:
        return up
    if kind == 3:
        return (left + up) // 2
    estimate = left + up - corner
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
    return (left, up, corner)[distances.index(min(distances))]


def differing_share(first: list[bytes], second: list[bytes]) -> float:
    total = sum(len(row) for row in first)
    changed = sum(
        a != b
        for row_a, row_b in zip(first, second, strict=True)
        for a, b in zip(row_a, row_b, strict=True)
    )
    return changed / total


Session = tuple[Kicad, Path, Path]


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Session:
    # KiCad, the original project and a copy with both packages adopted.
    root = tmp_path_factory.mktemp("kicad")
    before = root / "before"
    after = root / "after"
    shutil.copytree(FIXTURES / "project", before)
    shutil.copytree(FIXTURES / "project", after)
    env = load_env(stock_environ(DEMO_KICAD, root / "home"))
    web = FakeWeb({"https://example.com/acme/ldo.pdf": b"%PDF-1.4 ldo"})
    request = Request(
        after,
        "Local",
        prefixes=["PCM_ACME", "PCM_Other"],
        datasheets_dir=after / "docs",
        update_project=True,
    )
    apply(plan(request, env, web))
    return Kicad(root), before, after


def test_fixture_matches_its_libraries(session: Session) -> None:
    kicad, before, _ = session

    assert kicad.problems(before, packages=True) == {}


def test_check_notices_missing_packages(session: Session) -> None:
    kicad, before, _ = session

    assert kicad.problems(before, packages=False) != {}


def test_finds_every_adopted_part_without_packages(session: Session) -> None:
    kicad, _, after = session

    assert kicad.problems(after, packages=False) == {}


def test_render_notices_missing_models(session: Session) -> None:
    kicad, before, _ = session

    original = kicad.render(before, "original", packages=True)
    missing = kicad.render(before, "missing", packages=False)

    assert differing_share(original, missing) > 0.005


def test_renders_board_as_before_without_packages(session: Session) -> None:
    kicad, before, after = session

    original = kicad.render(before, "original", packages=True)
    adopted = kicad.render(after, "adopted", packages=False)

    assert differing_share(original, adopted) == 0


def test_project_stays_consistent_after_every_step(session: Session, tmp_path: Path) -> None:
    kicad, _, _ = session
    project = tmp_path / "steps"
    shutil.copytree(FIXTURES / "project", project)
    env = load_env(stock_environ(DEMO_KICAD, tmp_path / "home"))
    steps: list[dict[str, Any]] = [
        {"symbol_footprints": ["PCM_ACME_Regulator:LDO_A"]},
        # Shares the footprint, model and parent with the first step.
        {"symbol_footprints": ["PCM_ACME_Regulator:LDO_B"]},
        {"footprints": ["PCM_ACME_Passive:C_0805_Special"]},
        {"prefixes": ["PCM_ACME", "PCM_Other"]},
    ]

    for options in steps:
        apply(plan(Request(project, "Local", update_project=True, **options), env, FakeWeb()))
        assert kicad.problems(project, packages=True) == {}, options

    assert kicad.problems(project, packages=False) == {}
