from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from kiadopt import KicadEnv, Plan, Request, apply, load_env, plan
from tests.helpers import DEMO_KICAD, FIXTURES, MINI, PDF, FakeWeb, stock_environ

Adopt = Callable[..., Plan]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="rewrite tests/fixtures/expected from the current output",
    )


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb(
        {
            "https://example.com/acme/ldo.pdf": PDF + b"ldo",
            "https://example.com/acme/dfn.pdf": PDF + b"dfn",
            "https://example.com/acme/ldo-c.pdf": b"<html>not a pdf</html>",
            "https://example.com/mini/base.pdf": PDF + b"base",
            "https://example.com/mini/qfn.pdf": PDF + b"qfn",
        }
    )


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    shutil.copytree(FIXTURES / "project", project)
    return project


@pytest.fixture
def demo_env(tmp_path: Path) -> KicadEnv:
    return load_env(stock_environ(DEMO_KICAD, tmp_path / "home"))


@pytest.fixture
def mini(tmp_path: Path) -> Path:
    project = tmp_path / "mini"
    shutil.copytree(MINI / "project", project)
    return project


@pytest.fixture
def mini_env(tmp_path: Path) -> KicadEnv:
    return load_env(stock_environ(MINI, tmp_path / "home"))


@pytest.fixture
def adopt(web: FakeWeb) -> Adopt:
    def run(project: Path, env: KicadEnv, target: str = "Local", **options: Any) -> Plan:
        result = plan(Request(project, target, **options), env, web)
        apply(result)
        return result

    return run
