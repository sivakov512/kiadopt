# kiadopt

Moves parts from KiCad 10 libraries (PCM packages, stock or your global
libraries) into a library that lives in the project. Useful before handing a
project over to someone who doesn't have your packages installed.

A symbol comes with its parent symbols (`extends`), a footprint with its 3D
models, and datasheets are copied on request. With `--update-project` the
schematic and the board are switched over to the project library.

## Install

```bash
brew install sivakov512/tap/kiadopt
```

Or with uv, which needs Python 3.10+:

```bash
uv tool install git+https://github.com/sivakov512/kiadopt
```

## Usage

```
kiadopt [-sf ID] [-s ID] [-f ID] [--from PREFIX] --to LIB
        [--project DIR] [--lib-dir DIR] [--models DIR] [--datasheets [DIR]]
        [--update-project] [--dry-run]
```

`ID` is a library id, `Nickname:Name`, e.g. `Device:R`. `-sf`, `-s`, `-f` and
`--from` can be repeated and combined; at least one of them is required.

| Option | Meaning |
| --- | --- |
| `-sf ID`, `--symbol-footprint ID` | Symbol plus the footprint from its Footprint field. Fails if the field is empty or the footprint is missing. |
| `-s ID`, `--symbol ID` | Symbol only. Its Footprint field is left as is. |
| `-f ID`, `--footprint ID` | Footprint only. |
| `--from PREFIX` | Everything the project uses from libraries named `PREFIX` or `PREFIX_*`: symbols from all sheets, footprints from symbol fields and from the board. A symbol's footprint comes along if it is from such a library too. |
| `--to LIB` | Nickname of the project library. Required. If `LIB` is in the project `sym-lib-table`/`fp-lib-table`, the paths from there are used. Otherwise `LIB.kicad_sym` and `LIB.pretty` are created and registered. A global library, one outside the project or one of the `--from` libraries is refused. |
| `--project DIR` | Project folder or its `.kicad_pro`. Default: current folder. |
| `--lib-dir DIR` | Where a new `LIB` is created. Default: `libs` in the project. Ignored when `LIB` is already registered. |
| `--models DIR` | Where 3D models are copied. Default: `LIB.3dshapes` next to `LIB.pretty`. |
| `--datasheets [DIR]` | Download or copy datasheets. Default folder: `docs`. Without the option datasheets are not touched. |
| `--update-project` | Relink sheets and board to `LIB`: lib ids, schematic symbol cache, Footprint, Datasheet and footprint filter fields, model paths. Refuses to run while KiCad has the project open. |
| `--dry-run` | Show what would be done and write nothing. |

Relative paths are taken from the current folder. Paths inside the project are
written to KiCad files as `${KIPRJMOD}/...`, others as absolute paths.

Examples, for a project that keeps its parts in `libs/Local.kicad_sym`,
`libs/Local.pretty` and `libs/Local.3dshapes`:

```bash
kiadopt -sf PCM_SKC_Package_DFN:Maxim_TDFN-8-EP_2x2 --to Local
kiadopt -s Device:R -f Resistor_SMD:R_0805_2012Metric --to Local --datasheets
kiadopt --from PCM_SKC --to Local --models libs/3dshapes --update-project --dry-run
```

Output is one line per action, paths relative to the project:

```
symbol     PCM_SKC_Regulator_Linear:Rohm_BDXXKA5WF  ->  libs/Local.kicad_sym
footprint  PCM_SKC_Package_SO:SOP-8_4.4x5.35mm_P1.27mm  ->  libs/Local.pretty/SOP-8_4.4x5.35mm_P1.27mm.kicad_mod  (Rohm_BDXXKA5WF)
3D model   ${KICAD9_3DMODEL_DIR}/Package_SO.3dshapes/SOP-8.step  ->  libs/Local.3dshapes/SOP-8.step  (SOP-8_4.4x5.35mm_P1.27mm)
relink     demo.kicad_sch  (4 references)
skip       Local:SIMCom_A7672X  already in Local
Backup: demo-backups/adopt-20261013-120000
```

Exit code is 0 on success or when there is nothing to do, 1 on errors (printed
to stderr, nothing is written) and 2 on bad arguments.

## How it behaves

- Libraries are looked up like KiCad does: project table, then the global one
  (nested tables included). A `PCM_<name>` library missing from the tables is
  searched in the PCM install folder.
- A footprint used by several symbols, a model used by several footprints, a
  shared datasheet or parent symbol is copied once.
- Parts already in `LIB` are not overwritten. They show up as `skip`, with a
  warning if they differ from the source.
- Before writing, every file that will change is copied to
  `<project>-backups/adopt-<time>/`.
- Files are edited in place: only the changed values are rewritten, the rest
  stays byte for byte.
- If anything fails, nothing is written. Running the same command again does
  nothing.

From Python: `kiadopt.plan(...)` returns a `Plan` to look at, `kiadopt.apply(plan)`
writes it.

## Limitations

- KiCad 10 only.
- `LIB` must be a single `.kicad_sym` file, not a folder library.
- With `--from`, a symbol missing from its library is taken from the schematic
  cache (with a warning), but a missing footprint is an error.
- Only PDFs are saved as datasheets; other links are kept.

## Development

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest            # unit tests, no KiCad needed
uv run pytest -m kicad   # integration tests, need kicad-cli
```

Code layout: `plan.py` is the entry point. It finds the target library
(`target.py`), collects the parts to copy (`parts.py`, `symbols.py`), places 3D
models and datasheets (`assets.py`) and rewrites references (`relink.py`).
`apply.py` writes the result, `cli.py` parses arguments and prints the report.
Files are read with a small s-expression scanner (`sexpr.py`) that keeps offsets,
so values are replaced in place.

The test project in `tests/fixtures/project` is generated by
`uv run python tests/make_fixtures.py`. Expected outputs live in
`tests/fixtures/expected`; update them with
`uv run pytest tests/test_scenarios.py --update-golden` and review the diff.

Releases are cut by [release-please](https://github.com/googleapis/release-please):
every push to `main` updates a standing release PR with the next version and
the changelog from the conventional commits. Merging that PR tags `vX.Y.Z`, and
the release build runs the checks on the tag, attaches the sdist and wheel and
points the formula in
[sivakov512/homebrew-tap](https://github.com/sivakov512/homebrew-tap) at the new
wheel.
