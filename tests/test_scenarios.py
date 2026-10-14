# The main runs on the generated KiCad project. Each run is compared with the
# expected files, and every changed file with the original token by token: a
# token may differ only where a reference to an adopted part lives, and only by
# becoming the reference to its copy. Refresh the expected files with
# `pytest tests/test_scenarios.py --update-golden` and review the diff.

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from kiadopt import KicadEnv, Request, apply, plan
from kiadopt.cli import report_lines
from kiadopt.sexpr import Atom, Node, parse
from tests.helpers import FIXTURES, FakeWeb, snapshot

ORIGINAL = FIXTURES / "project"
EXPECTED = FIXTURES / "expected"
PROJECT_FILES = ("demo.kicad_sch", "channel.kicad_sch", "demo.kicad_pcb")

SCENARIOS: dict[str, dict[str, Any]] = {
    "symbol-footprint": {"symbol_footprints": ["PCM_ACME_Regulator:LDO_B"]},
    "symbol-footprint-update": {
        "symbol_footprints": ["PCM_ACME_Regulator:LDO_B"],
        "update_project": True,
    },
    "symbol": {"symbols": ["PCM_ACME_Sensor:Sensor"], "datasheets": True},
    "footprint": {"footprints": ["PCM_ACME_Package_SO:SOIC-8_EP"]},
    "from": {"prefixes": ["PCM_ACME"], "datasheets": True},
    "from-update": {"prefixes": ["PCM_ACME"], "datasheets": True, "update_project": True},
    "new-library-update": {
        "target": "Adopted",
        "prefixes": ["PCM_ACME"],
        "datasheets": True,
        "update_project": True,
    },
}


def target_of(name: str) -> str:
    target: str = SCENARIOS[name].get("target", "Local")
    return target


def run_scenario(name: str, project: Path, env: KicadEnv, web: FakeWeb) -> dict[str, bytes]:
    """New and changed project files after the run, plus the printed report."""
    options = dict(SCENARIOS[name])
    options.pop("target", None)
    if options.pop("datasheets", False):
        options["datasheets_dir"] = project / "docs"
    result = plan(Request(project, target_of(name), **options), env, web)
    apply(result)
    original = snapshot(ORIGINAL)
    changed = {
        path: data
        for path, data in snapshot(project).items()
        if not path.startswith("demo-backups/") and original.get(path) != data
    }
    changed["report.txt"] = ("\n".join(report_lines(result)) + "\n").encode()
    return changed


@pytest.mark.parametrize("name", SCENARIOS)
def test_matches_expected_files_and_report(
    name: str, demo: Path, demo_env: KicadEnv, web: FakeWeb, request: pytest.FixtureRequest
) -> None:
    changed = run_scenario(name, demo, demo_env, web)

    expected = EXPECTED / name
    if request.config.getoption("--update-golden"):
        shutil.rmtree(expected, ignore_errors=True)
        for path, data in changed.items():
            (expected / path).parent.mkdir(parents=True, exist_ok=True)
            (expected / path).write_bytes(data)
    assert changed == snapshot(expected)
    assert set(snapshot(ORIGINAL)) <= set(snapshot(demo)), "a project file was deleted"


UPDATING = [name for name, options in SCENARIOS.items() if options.get("update_project")]


@dataclass(frozen=True)
class Place:
    head: str
    parent: str
    index: int
    property: str


def tokens_with_places(node: Node, parent: str = "") -> list[tuple[str, Place | None]]:
    result: list[tuple[str, Place | None]] = [("(", None)]
    name = node.atom(1)
    prop = name.value if node.head == "property" and name is not None else ""
    for index, item in enumerate(node.items):
        if isinstance(item, Atom):
            result.append((item.value, Place(node.head, parent, index, prop)))
        else:
            result += tokens_with_places(item, node.head)
    return [*result, (")", None)]


def skeleton(text: str) -> str:
    spans = []
    stack = [parse(text)]
    while stack:
        node = stack.pop()
        for item in node.items:
            if isinstance(item, Node):
                stack.append(item)
            elif text.startswith('"', item.start):
                spans.append((item.start, item.end))
    pieces, position = [], 0
    for start, end in sorted(spans):
        pieces += [text[position:start], '""']
        position = end
    return "".join([*pieces, text[position:]])


def adopted(lib_id: str, target: str) -> str:
    return f"{target}:{lib_id.partition(':')[2]}"


def is_expected_replacement(place: Place, old: str, new: str, target: str) -> bool:
    from_acme = old.startswith("PCM_ACME")
    if place.head == "lib_id" or (place.head == "symbol" and place.parent == "lib_symbols"):
        return from_acme and new == adopted(old, target)
    if place.head == "footprint" and place.parent == "kicad_pcb" and place.index == 1:
        return from_acme and new == adopted(old, target)
    if place.head == "model":
        return new == f"${{KIPRJMOD}}/libs/{target}.3dshapes/{PurePosixPath(old).name}"
    if place.head == "descr":
        return new == re.sub(r"https://\S+/(\w+\.pdf)", r"${KIPRJMOD}/docs/\1", old)
    if place.head != "property" or place.index != 2:
        return False
    if place.property == "Footprint":
        return from_acme and new == adopted(old, target)
    if place.property == "Datasheet":
        return new == f"${{KIPRJMOD}}/docs/{PurePosixPath(old).name}"
    if place.property == "ki_fp_filters":
        return new == re.sub(r"PCM_ACME\w*:", f"{target}:", old)
    return False


def unexpected_changes(before: str, after: str, target: str) -> list[str]:
    if skeleton(after) != skeleton(before):
        return ["whitespace or structure changed"]
    old_tokens = tokens_with_places(parse(before))
    new_tokens = tokens_with_places(parse(after))
    return [
        f"{place}: {old!r} -> {new!r}"
        for (old, place), (new, _) in zip(old_tokens, new_tokens, strict=True)
        if old != new and (place is None or not is_expected_replacement(place, old, new, target))
    ]


@pytest.mark.parametrize("name", UPDATING)
def test_schematics_and_board_change_only_in_adopted_references(
    name: str, demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    changed = run_scenario(name, demo, demo_env, web)

    original = snapshot(ORIGINAL)
    for path in PROJECT_FILES:
        before = original[path].decode()
        after = changed.get(path, original[path]).decode()
        assert unexpected_changes(before, after, target_of(name)) == [], path


@pytest.mark.parametrize("name", SCENARIOS)
def test_libraries_and_tables_only_get_new_entries_at_the_end(
    name: str, demo: Path, demo_env: KicadEnv, web: FakeWeb
) -> None:
    changed = run_scenario(name, demo, demo_env, web)

    original = snapshot(ORIGINAL)
    for path in set(changed) & set(original) - set(PROJECT_FILES):
        before, after = original[path].decode(), changed[path].decode()
        closing = before.rindex(")")
        assert after.startswith(before[:closing]), path
        assert after.endswith(before[closing:]), path


SHEET = (ORIGINAL / "demo.kicad_sch").read_bytes().decode()


def test_check_catches_change_of_unrelated_value() -> None:
    after = SHEET.replace('(property "Value" "10k"', '(property "Value" "22k"', 1)

    assert unexpected_changes(SHEET, after, "Local") == [
        "Place(head='property', parent='symbol', index=2, property='Value'): '10k' -> '22k'"
    ]


def test_check_catches_relinked_part_of_other_library() -> None:
    after = SHEET.replace('(lib_id "Device:R")', '(lib_id "Local:R")', 1)

    assert len(unexpected_changes(SHEET, after, "Local")) == 1


def test_check_catches_reformatting() -> None:
    after = SHEET.replace("\t(paper", "  (paper")

    assert unexpected_changes(SHEET, after, "Local") == ["whitespace or structure changed"]
