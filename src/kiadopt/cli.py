from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path

from kiadopt.apply import apply
from kiadopt.env import display_path, load_env
from kiadopt.errors import AdoptError
from kiadopt.fetch import fetch
from kiadopt.plan import Action, Plan, Request, plan

DEFAULT_DATASHEETS_DIR = "docs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kiadopt",
        description="Copy parts from any KiCad library into a project library.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('kiadopt')}")
    what = parser.add_argument_group("what to adopt (repeatable, at least one)")
    # Must be a separate option: argparse would read "-sf X" as "-s f".
    what.add_argument(
        "-sf",
        "--symbol-footprint",
        action="append",
        default=[],
        metavar="ID",
        help="symbol, its footprint and their 3D models and datasheets",
    )
    what.add_argument(
        "-s", "--symbol", action="append", default=[], metavar="ID", help="symbol only"
    )
    what.add_argument(
        "-f", "--footprint", action="append", default=[], metavar="ID", help="footprint only"
    )
    what.add_argument(
        "--from",
        dest="prefixes",
        action="append",
        default=[],
        metavar="PREFIX",
        help="everything the project uses from libraries PREFIX and PREFIX_*",
    )
    parser.add_argument("--to", required=True, metavar="LIB", help="project library nickname")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(),
        metavar="DIR",
        help="project folder or .kicad_pro (default: current folder)",
    )
    parser.add_argument(
        "--lib-dir",
        type=Path,
        metavar="DIR",
        help="folder for a new LIB (default: libs in the project)",
    )
    parser.add_argument(
        "--models",
        type=Path,
        metavar="DIR",
        help="folder for 3D models (default: LIB.3dshapes next to LIB.pretty)",
    )
    parser.add_argument(
        "--datasheets",
        type=Path,
        nargs="?",
        const=Path(DEFAULT_DATASHEETS_DIR),
        metavar="DIR",
        help=f"copy datasheets (default folder: {DEFAULT_DATASHEETS_DIR})",
    )
    parser.add_argument(
        "--update-project", action="store_true", help="point the schematic and board at LIB"
    )
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.symbol_footprint or args.symbol or args.footprint or args.prefixes):
        parser.error("give at least one of -sf, -s, -f or --from")
    request = Request(
        project=args.project.absolute(),
        target=args.to,
        symbol_footprints=args.symbol_footprint,
        symbols=args.symbol,
        footprints=args.footprint,
        prefixes=args.prefixes,
        lib_dir=_absolute(args.lib_dir),
        models_dir=_absolute(args.models),
        datasheets_dir=_absolute(args.datasheets),
        update_project=args.update_project,
    )
    try:
        result = plan(request, load_env(os.environ if environ is None else environ), fetch)
        for line in report_lines(result):
            print(line)
        if not result.has_changes:
            print("Nothing to do.")
        elif args.dry_run:
            print("Dry run: nothing written.")
        else:
            applied = apply(result)
            if applied.backup_dir is not None:
                print(f"Backup: {display_path(applied.backup_dir, result.project.dir)}")
    except (AdoptError, OSError) as exc:
        for line in str(exc).splitlines():
            print(f"error: {line}", file=sys.stderr)
        return 1
    return 0


def _absolute(path: Path | None) -> Path | None:
    return path.absolute() if path is not None else None


def report_lines(result: Plan) -> list[str]:
    lines = [format_action(action) for action in result.actions]
    return lines + [f"{'warning':<11}{warning}" for warning in result.warnings]


def format_action(action: Action) -> str:
    line = f"{action.kind:<11}{action.subject}"
    if action.target:
        line += f"  ->  {action.target}"
    if action.users:
        line += f"  ({', '.join(action.users)})"
    if action.detail:
        line += f"  {action.detail}"
    return line
