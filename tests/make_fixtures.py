# Generates tests/fixtures/kicad and tests/fixtures/project. Needs KiCad 10:
# stock parts are copied from the local installation (KICAD_STOCK overrides the
# path) and every file is normalized with kicad-cli.
#
#     uv run python tests/make_fixtures.py

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from kiadopt import sexpr

FIXTURES = Path(__file__).parent / "fixtures"
KICAD = FIXTURES / "kicad"
PROJECT = FIXTURES / "project"
STOCK_SOURCE = Path(
    os.environ.get("KICAD_STOCK", "/Applications/KiCad/KiCad.app/Contents/SharedSupport")
)

ACME = "com_github_acme_kicad-library"
OTHER = "com_github_other_kicad-library"
NAMESPACE = uuid.UUID("5d0c7a52-8a43-4c4e-9a59-6f1ab2d0c0de")
FAKE_PDF = b"%PDF-1.4\n% kiadopt test datasheet\n%%EOF\n"


def name_atom(node: sexpr.Node) -> sexpr.Atom:
    atom = node.atom(1)
    assert atom is not None
    return atom


def uid(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    kind: str
    x: float
    y: float
    angle: int


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    value: str
    footprint: str
    datasheet: str
    description: str
    reference: str = "U"
    fp_filters: str = ""
    pins: tuple[Pin, ...] = ()
    size: tuple[float, float] = (10.16, 7.62)
    extends: str | None = None


@dataclass(frozen=True)
class FootprintSpec:
    name: str
    descr: str
    pads: int
    pitch: float
    span: float
    model: str | None
    size: tuple[float, float, float] = (5.0, 4.0, 1.5)
    color: tuple[float, float, float] = (0.2, 0.2, 0.2)
    datasheet: str = ""


@dataclass
class Placed:
    reference: str
    lib_id: str
    footprint: str
    value: str
    at: tuple[float, float]
    sheet_refs: tuple[str, ...] = ()
    board_at: tuple[float, float] = (0, 0)


def regulator_pins() -> tuple[Pin, ...]:
    return (
        Pin("1", "VIN", "power_in", -7.62, 2.54, 0),
        Pin("2", "GND", "power_in", 0, -6.35, 90),
        Pin("3", "VOUT", "power_out", 7.62, 2.54, 180),
    )


def sensor_pins() -> tuple[Pin, ...]:
    return (
        Pin("1", "VDD", "power_in", -7.62, 2.54, 0),
        Pin("2", "GND", "power_in", -7.62, 0, 0),
        Pin("3", "SDA", "bidirectional", 7.62, 2.54, 180),
        Pin("4", "SCL", "input", 7.62, 0, 180),
        Pin("5", "INT", "output", 7.62, -2.54, 180),
        Pin("6", "NC", "no_connect", -7.62, -2.54, 0),
    )


def two_pins() -> tuple[Pin, ...]:
    return (Pin("1", "~", "passive", -7.62, 0, 0), Pin("2", "~", "passive", 7.62, 0, 180))


LDO_DATASHEET = "https://example.com/acme/ldo.pdf"
SO_FILTERS = "PCM_ACME_Package_SO:SOIC-8* SOT?23*"
LDO_A = SymbolSpec(
    "LDO_A",
    "LDO_A",
    "PCM_ACME_Package_SO:SOIC-8",
    LDO_DATASHEET,
    "Low dropout regulator, 3.3 V",
    fp_filters=SO_FILTERS,
    pins=regulator_pins(),
)
LDO_B = replace(LDO_A, name="LDO_B", value="LDO_B", description="LDO, 5 V", extends="LDO_A")
LDO_C = replace(
    LDO_A,
    name="LDO_C",
    value="LDO_C",
    footprint="PCM_ACME_Package_SO:SOIC-8_EP",
    datasheet="https://example.com/acme/ldo-c.pdf",
    description="LDO with exposed pad",
    extends="LDO_A",
)
SENSOR = SymbolSpec(
    "Sensor",
    "Sensor",
    "PCM_ACME_Package_DFN:DFN-6",
    f"${{KICAD10_3RD_PARTY}}/resources/{ACME}/sensor.pdf",
    "Temperature sensor, I2C",
    fp_filters="PCM_ACME_Package_DFN:DFN*",
    pins=sensor_pins(),
)
THING = SymbolSpec(
    "Thing",
    "Thing",
    "PCM_Other_Misc:Thing_FP",
    "https://example.com/other/thing.pdf",
    "Something from another package",
    reference="X",
    pins=two_pins(),
)
EXISTING = SymbolSpec(
    "Existing",
    "Existing",
    "Local:Existing_FP",
    "",
    "Part already in the project library",
    reference="X",
    pins=two_pins(),
)

SO_MODEL = f"3dmodels/{ACME}/ACME_Package_SO.3dshapes/SOIC-8.wrl"
SOIC_8 = FootprintSpec(
    "SOIC-8",
    "SOIC, 8 pins, 3.9x4.9 mm, pitch 1.27 mm",
    8,
    1.27,
    5.4,
    "${KICAD8_3RD_PARTY}/" + SO_MODEL,
)
SOIC_8_EP = replace(
    SOIC_8,
    name="SOIC-8_EP",
    descr="SOIC, 8 pins, exposed pad",
    model="${KICAD10_3RD_PARTY}/" + SO_MODEL,
)
DFN_6 = FootprintSpec(
    "DFN-6",
    "DFN, 6 pins, 2x2 mm, see https://example.com/acme/dfn.pdf",
    6,
    0.65,
    2.0,
    f"${{KICAD10_3RD_PARTY}}/3dmodels/{ACME}/ACME_Package_DFN.3dshapes/DFN-6.wrl",
    size=(2.0, 2.0, 0.8),
    color=(0.1, 0.2, 0.7),
)
C_SPECIAL = FootprintSpec(
    "C_0805_Special",
    "Capacitor 0805 with a custom model",
    2,
    0,
    2.0,
    f"${{KICAD10_3RD_PARTY}}/3dmodels/{ACME}/ACME_Passive.3dshapes/C_0805_Special.wrl",
    size=(2.0, 1.25, 1.0),
    color=(0.75, 0.6, 0.3),
)
THING_FP = FootprintSpec(
    "Thing_FP",
    "Footprint from another package",
    2,
    0,
    4.0,
    f"${{KICAD10_3RD_PARTY}}/3dmodels/{OTHER}/Other_Misc.3dshapes/Thing.wrl",
    size=(4.0, 2.0, 2.0),
    color=(0.1, 0.6, 0.2),
)
EXISTING_FP = FootprintSpec(
    "Existing_FP",
    "Footprint already in the project library",
    2,
    0,
    3.0,
    "${KIPRJMOD}/libs/Local.3dshapes/Existing.wrl",
    size=(3.0, 1.5, 1.2),
    color=(0.7, 0.1, 0.1),
)


def main() -> None:
    for folder in (KICAD, PROJECT):
        shutil.rmtree(folder, ignore_errors=True)
    write_stock()
    write_packages()
    write_config()
    write_project_files()
    with tempfile.TemporaryDirectory() as config_home:
        environment = kicad_environment(Path(config_home))
        normalize_libraries(environment)
        write_board()
        write_schematics()
        run(["pcb", "upgrade", "--force", str(PROJECT / "demo.kicad_pcb")], environment)
        for sheet in ("demo.kicad_sch", "channel.kicad_sch"):
            run(["sch", "upgrade", "--force", str(PROJECT / sheet)], environment)
    # kicad-cli leaves editor state behind; it is not part of the fixture.
    (PROJECT / "demo.kicad_prl").unlink(missing_ok=True)


def kicad_environment(config_home: Path) -> dict[str, str]:
    # kicad-cli rewrites kicad_common.json on every run, so it gets a config of its own.
    shutil.copytree(KICAD / "config", config_home, dirs_exist_ok=True)
    return {
        **os.environ,
        "KICAD_CONFIG_HOME": str(config_home),
        **fixture_variables(),
    }


def fixture_variables() -> dict[str, str]:
    stock = KICAD / "stock"
    return {
        "KICAD10_3RD_PARTY": str(KICAD / "3rdparty"),
        "KICAD10_SYMBOL_DIR": str(stock / "symbols"),
        "KICAD10_FOOTPRINT_DIR": str(stock / "footprints"),
        "KICAD10_3DMODEL_DIR": str(stock / "3dmodels"),
        "KICAD10_TEMPLATE_DIR": str(stock / "template"),
    }


def run(arguments: list[str], environment: dict[str, str]) -> None:
    subprocess.run(["nice", "kicad-cli", *arguments], env=environment, check=True)


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode()
    path.write_bytes(content)


def write_stock() -> None:
    stock = KICAD / "stock"
    device = (STOCK_SOURCE / "symbols" / "Device.kicad_sym").read_text()
    root = sexpr.parse(device)
    blocks = [
        sexpr.line_block(device, node)
        for node in root.children("symbol")
        if name_atom(node).value in ("R", "C")
    ]
    header = "".join(
        "\t" + device[node.start : node.end] + "\n"
        for node in root.items[1:]
        if isinstance(node, sexpr.Node) and node.head != "symbol"
    )
    write(
        stock / "symbols/Device.kicad_sym",
        f"(kicad_symbol_lib\n{header}{''.join(b + chr(10) for b in blocks)})\n",
    )
    for library, name, color in (
        ("Resistor_SMD", "R_0805_2012Metric", (0.1, 0.1, 0.1)),
        ("Capacitor_SMD", "C_0805_2012Metric", (0.8, 0.7, 0.5)),
    ):
        text = (STOCK_SOURCE / "footprints" / f"{library}.pretty" / f"{name}.kicad_mod").read_text()
        write(
            stock / f"footprints/{library}.pretty/{name}.kicad_mod",
            with_uuids(text.replace(f"{name}.step", f"{name}.wrl"), name),
        )
        write(stock / f"3dmodels/{library}.3dshapes/{name}.wrl", box_model((2.0, 1.25, 0.5), color))
    write(
        stock / "template/sym-lib-table",
        table("sym_lib_table", [("Device", "${KICAD10_SYMBOL_DIR}/Device.kicad_sym")]),
    )
    write(
        stock / "template/fp-lib-table",
        table(
            "fp_lib_table",
            [
                ("Resistor_SMD", "${KICAD10_FOOTPRINT_DIR}/Resistor_SMD.pretty"),
                ("Capacitor_SMD", "${KICAD10_FOOTPRINT_DIR}/Capacitor_SMD.pretty"),
            ],
        ),
    )


def with_uuids(text: str, name: str) -> str:
    # kicad-cli gives items without a UUID a random one, which would make every
    # run produce different files. The same goes for the Datasheet and
    # Description fields that KiCad adds to stock footprints.
    root = sexpr.parse(text)
    edits = [
        (node.end - 1, node.end - 1, f' (uuid "{uid(f"{name}-{index}")}")')
        for index, node in enumerate(root.items)
        if isinstance(node, sexpr.Node) and node.head in UUID_ITEMS and node.child("uuid") is None
    ]
    last_property = list(root.children("property"))[-1]
    fields = "".join(
        f'\n\t(property "{field}" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
        f' (uuid "{uid(f"{name}-{field}")}") (effects (font (size 1.27 1.27))))'
        for field in ("Datasheet", "Description")
        if root.property(field) is None
    )
    edits.append((last_property.end, last_property.end, fields))
    return sexpr.splice(text, edits)


UUID_ITEMS = {"property", "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_text", "pad"}


def write_packages() -> None:
    third = KICAD / "3rdparty"
    write(third / f"symbols/{ACME}/ACME_Regulator.kicad_sym", symbol_library([LDO_A, LDO_B, LDO_C]))
    write(third / f"symbols/{ACME}/ACME_Sensor.kicad_sym", symbol_library([SENSOR]))
    write(third / f"symbols/{OTHER}/Other_Misc.kicad_sym", symbol_library([THING]))
    for package, library, spec in (
        (ACME, "ACME_Package_SO", SOIC_8),
        (ACME, "ACME_Package_SO", SOIC_8_EP),
        (ACME, "ACME_Package_DFN", DFN_6),
        (ACME, "ACME_Passive", C_SPECIAL),
        (OTHER, "Other_Misc", THING_FP),
    ):
        write(
            third / f"footprints/{package}/{library}.pretty/{spec.name}.kicad_mod",
            footprint_text(spec),
        )
        assert spec.model is not None
        model = spec.model.replace("${KICAD8_3RD_PARTY}/", "").replace("${KICAD10_3RD_PARTY}/", "")
        write(third / model, box_model(spec.size, spec.color))
    write(third / f"resources/{ACME}/sensor.pdf", FAKE_PDF)


def write_config() -> None:
    config = KICAD / "config" / "10.0"
    pcm = "${KICAD10_3RD_PARTY}"
    write(
        config / "sym-lib-table",
        table(
            "sym_lib_table",
            [
                ("KiCad", "${KICAD10_TEMPLATE_DIR}/sym-lib-table", "Table"),
                ("PCM_ACME_Regulator", f"{pcm}/symbols/{ACME}/ACME_Regulator.kicad_sym"),
                ("PCM_ACME_Sensor", f"{pcm}/symbols/{ACME}/ACME_Sensor.kicad_sym"),
                ("PCM_Other_Misc", f"{pcm}/symbols/{OTHER}/Other_Misc.kicad_sym"),
            ],
        ),
    )
    write(
        config / "fp-lib-table",
        table(
            "fp_lib_table",
            [
                ("KiCad", "${KICAD10_TEMPLATE_DIR}/fp-lib-table", "Table"),
                ("PCM_ACME_Package_SO", f"{pcm}/footprints/{ACME}/ACME_Package_SO.pretty"),
                ("PCM_ACME_Package_DFN", f"{pcm}/footprints/{ACME}/ACME_Package_DFN.pretty"),
                ("PCM_ACME_Passive", f"{pcm}/footprints/{ACME}/ACME_Passive.pretty"),
                ("PCM_Other_Misc", f"{pcm}/footprints/{OTHER}/Other_Misc.pretty"),
            ],
        ),
    )


def write_project_files() -> None:
    write(
        PROJECT / "demo.kicad_pro",
        '{\n  "meta": {\n    "filename": "demo.kicad_pro",\n    "version": 3\n  }\n}\n',
    )
    write(
        PROJECT / "sym-lib-table",
        table("sym_lib_table", [("Local", "${KIPRJMOD}/libs/Local.kicad_sym")]),
    )
    write(
        PROJECT / "fp-lib-table",
        table("fp_lib_table", [("Local", "${KIPRJMOD}/libs/Local.pretty")]),
    )
    write(PROJECT / "libs/Local.kicad_sym", symbol_library([EXISTING]))
    write(PROJECT / "libs/Local.pretty/Existing_FP.kicad_mod", footprint_text(EXISTING_FP))
    write(
        PROJECT / "libs/Local.3dshapes/Existing.wrl", box_model(EXISTING_FP.size, EXISTING_FP.color)
    )


def normalize_libraries(environment: dict[str, str]) -> None:
    for library in sorted(KICAD.rglob("*.kicad_sym")) + sorted(PROJECT.rglob("*.kicad_sym")):
        if "stock" not in library.parts:
            run(["sym", "upgrade", "--force", str(library)], environment)
    for library in sorted(KICAD.rglob("*.pretty")) + sorted(PROJECT.rglob("*.pretty")):
        if "stock" not in library.parts:
            run(["fp", "upgrade", "--force", str(library)], environment)


def table(root: str, entries: list[tuple[str, ...]]) -> str:
    lines = [f"({root}", "\t(version 7)"]
    for name, uri, *kind in entries:
        lib_type = kind[0] if kind else "KiCad"
        lines.append(
            f'\t(lib (name "{name}") (type "{lib_type}") (uri "{uri}") (options "") (descr ""))'
        )
    return "\n".join(lines) + "\n)\n"


def box_model(size: tuple[float, float, float], color: tuple[float, float, float]) -> str:
    # KiCad reads VRML in units of 0.1 inch.
    x, y, z = (value / 2.54 for value in size)
    corners = [
        (sx * x / 2, sy * y / 2, sz * z)
        for sz in (0, 1)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    points = ", ".join(f"{px:.4f} {py:.4f} {pz:.4f}" for px, py, pz in corners)
    indices = ", ".join(", ".join(str(index) for index in face) + ", -1" for face in faces)
    r, g, b = color
    return (
        "#VRML V2.0 utf8\n"
        "Shape {\n"
        f"  appearance Appearance {{ material Material {{ diffuseColor {r} {g} {b} }} }}\n"
        "  geometry IndexedFaceSet {\n"
        f"    coord Coordinate {{ point [ {points} ] }}\n"
        f"    coordIndex [ {indices} ]\n"
        "  }\n"
        "}\n"
    )


def symbol_library(specs: list[SymbolSpec]) -> str:
    body = "".join(symbol_text(spec, spec.name, 1) + "\n" for spec in specs)
    return f'(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "acme")\n{body})\n'


def _property(name: str, value: str, at: tuple[float, float], hidden: bool, indent: str) -> str:
    hide = " (hide yes)" if hidden else ""
    return (
        f'{indent}(property "{name}" "{value}" (at {at[0]} {at[1]} 0){hide}'
        " (effects (font (size 1.27 1.27))))\n"
    )


def symbol_properties(spec: SymbolSpec, indent: str) -> str:
    height = spec.size[1]
    text = _property("Reference", spec.reference, (0, height / 2 + 2.54), False, indent)
    text += _property("Value", spec.value, (0, -height / 2 - 2.54), False, indent)
    text += _property("Footprint", spec.footprint, (0, 0), True, indent)
    text += _property("Datasheet", spec.datasheet, (0, 0), True, indent)
    text += _property("Description", spec.description, (0, 0), True, indent)
    if spec.fp_filters:
        text += _property("ki_fp_filters", spec.fp_filters, (0, 0), True, indent)
    return text


def symbol_text(spec: SymbolSpec, name: str, depth: int, parent: SymbolSpec | None = None) -> str:
    # With `parent` this is the flattened copy KiCad keeps in the schematic cache.
    outer = "\t" * depth
    inner = outer + "\t"
    unit_name = name.partition(":")[2] or name
    if spec.extends and parent is None:
        properties = symbol_properties(spec, inner)
        return f'{outer}(symbol "{name}" (extends "{spec.extends}")\n{properties}{outer})'
    shape = parent or spec
    width, height = shape.size
    pins = "".join(
        f"{inner}\t(pin {pin.kind} line (at {pin.x} {pin.y} {pin.angle}) (length 2.54)"
        f' (name "{pin.name}" (effects (font (size 1.27 1.27))))'
        f' (number "{pin.number}" (effects (font (size 1.27 1.27)))))\n'
        for pin in shape.pins
    )
    return (
        f'{outer}(symbol "{name}" (pin_names (offset 0.254))'
        " (exclude_from_sim no) (in_bom yes) (on_board yes)\n"
        f"{symbol_properties(spec, inner)}"
        f'{inner}(symbol "{unit_name}_0_1" (rectangle'
        f" (start {-width / 2} {height / 2}) (end {width / 2} {-height / 2})"
        " (stroke (width 0.254) (type default)) (fill (type background))))\n"
        f'{inner}(symbol "{unit_name}_1_1"\n{pins}{inner})\n'
        f"{outer})"
    )


def footprint_text(spec: FootprintSpec) -> str:
    pads = []
    per_side = max(spec.pads // 2, 1)
    for index in range(spec.pads):
        side = -1 if index < per_side else 1
        row = index if index < per_side else spec.pads - 1 - index
        y = (row - (per_side - 1) / 2) * spec.pitch
        x = side * spec.span / 2
        pads.append(
            f'\t(pad "{index + 1}" smd roundrect (at {x:g} {y:g}) (size 1.2 0.6)'
            ' (layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.25)'
            f' (uuid "{uid(f"{spec.name}-pad-{index}")}"))\n'
        )
    width, height = spec.size[0], spec.size[1]

    def item_uuid(label: str) -> str:
        return f'(uuid "{uid(f"{spec.name}-{label}")}")'

    model = ""
    if spec.model:
        model = (
            f'\t(model "{spec.model}"'
            " (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n"
        )
    return (
        f'(footprint "{spec.name}" (version 20260206) (generator "acme") (layer "F.Cu")\n'
        f'\t(descr "{spec.descr}")\n'
        f'\t(property "Reference" "REF**" (at 0 {-height / 2 - 1.5:g} 0) (layer "F.SilkS")'
        f" {item_uuid('reference')} (effects (font (size 1 1) (thickness 0.15))))\n"
        f'\t(property "Value" "{spec.name}" (at 0 {height / 2 + 1.5:g} 0) (layer "F.Fab")'
        f" {item_uuid('value')} (effects (font (size 1 1) (thickness 0.15))))\n"
        f'\t(property "Datasheet" "{spec.datasheet}" (at 0 0 0) (layer "F.Fab") (hide yes)'
        f" {item_uuid('datasheet')} (effects (font (size 1 1) (thickness 0.15))))\n"
        '\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
        f" {item_uuid('description')} (effects (font (size 1 1) (thickness 0.15))))\n"
        "\t(attr smd)\n"
        f"\t(fp_rect (start {-width / 2:g} {-height / 2:g}) (end {width / 2:g} {height / 2:g})"
        f' (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab") {item_uuid("fab")})\n'
        f"\t(fp_rect (start {-width / 2 - 0.5:g} {-height / 2 - 0.5:g})"
        f" (end {width / 2 + 0.5:g} {height / 2 + 0.5:g})"
        f' (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd") {item_uuid("crtyd")})\n'
        f"{''.join(pads)}{model})\n"
    )


ROOT_PARTS = [
    Placed(
        "U1",
        "PCM_ACME_Regulator:LDO_A",
        "PCM_ACME_Package_SO:SOIC-8",
        "LDO_A",
        (60, 50),
        board_at=(100, 80),
    ),
    Placed(
        "U2",
        "PCM_ACME_Regulator:LDO_B",
        "PCM_ACME_Package_SO:SOIC-8",
        "LDO_B",
        (60, 80),
        board_at=(115, 80),
    ),
    Placed("R1", "Device:R", "Resistor_SMD:R_0805_2012Metric", "10k", (90, 50), board_at=(130, 80)),
    Placed(
        "C1", "Device:C", "PCM_ACME_Passive:C_0805_Special", "100n", (90, 80), board_at=(140, 80)
    ),
    Placed(
        "X1",
        "PCM_Other_Misc:Thing",
        "PCM_Other_Misc:Thing_FP",
        "Thing",
        (60, 110),
        board_at=(100, 95),
    ),
    Placed("X2", "Local:Existing", "Local:Existing_FP", "Existing", (90, 110), board_at=(115, 95)),
]
CHANNEL_PARTS = [
    Placed(
        "U3",
        "PCM_ACME_Sensor:Sensor",
        "PCM_ACME_Package_DFN:DFN-6",
        "Sensor",
        (60, 50),
        ("U3", "U4"),
    ),
    Placed(
        "U5",
        "PCM_ACME_Regulator:LDO_C",
        "PCM_ACME_Package_SO:SOIC-8_EP",
        "LDO_C",
        (60, 80),
        ("U5", "U6"),
    ),
    Placed("R2", "Device:R", "Resistor_SMD:R_0805_2012Metric", "4k7", (90, 50), ("R2", "R3")),
]
SHEETS = [("Channel A", (150, 40)), ("Channel B", (150, 80))]
CHANNEL_BOARD = {
    "U3": (100, 110),
    "U4": (110, 110),
    "U5": (125, 110),
    "U6": (140, 110),
    "R2": (150, 110),
    "R3": (155, 110),
}

SPECS = {
    "PCM_ACME_Regulator:LDO_A": LDO_A,
    "PCM_ACME_Regulator:LDO_B": LDO_B,
    "PCM_ACME_Regulator:LDO_C": LDO_C,
    "PCM_ACME_Sensor:Sensor": SENSOR,
    "PCM_Other_Misc:Thing": THING,
    "Local:Existing": EXISTING,
}


def write_board() -> None:
    footprints = []
    for part in ROOT_PARTS:
        footprints.append(
            board_footprint(part, part.reference, part.board_at, f"/{uid(part.reference)}", "/")
        )
    for index, (sheet_name, _) in enumerate(SHEETS):
        for part in CHANNEL_PARTS:
            reference = part.sheet_refs[index]
            path = f"/{uid(sheet_name)}/{uid(part.reference)}"
            footprints.append(
                board_footprint(part, reference, CHANNEL_BOARD[reference], path, f"/{sheet_name}/")
            )
    header = BOARD_HEADER.replace("@OUTLINE@", uid("outline"))
    write(PROJECT / "demo.kicad_pcb", header + "".join(footprints) + ")\n")


def library_footprint(lib_id: str) -> Path:
    nickname, _, name = lib_id.partition(":")
    folders = {
        "PCM_ACME_Package_SO": KICAD / f"3rdparty/footprints/{ACME}/ACME_Package_SO.pretty",
        "PCM_ACME_Package_DFN": KICAD / f"3rdparty/footprints/{ACME}/ACME_Package_DFN.pretty",
        "PCM_ACME_Passive": KICAD / f"3rdparty/footprints/{ACME}/ACME_Passive.pretty",
        "PCM_Other_Misc": KICAD / f"3rdparty/footprints/{OTHER}/Other_Misc.pretty",
        "Resistor_SMD": KICAD / "stock/footprints/Resistor_SMD.pretty",
        "Capacitor_SMD": KICAD / "stock/footprints/Capacitor_SMD.pretty",
        "Local": PROJECT / "libs/Local.pretty",
    }
    return folders[nickname] / f"{name}.kicad_mod"


def board_footprint(
    part: Placed, reference: str, at: tuple[float, float], path: str, sheet_name: str
) -> str:
    text = library_footprint(part.footprint).read_text()
    root = sexpr.parse(text)
    footprint_id = name_atom(root)
    edits = [(footprint_id.start, footprint_id.end, sexpr.quote(part.footprint))]
    for head in ("version", "generator", "generator_version"):
        node = root.child(head)
        if node is not None:
            start = text.rfind("\n", 0, node.start) + 1
            edits.append((start, node.end + 1, ""))
    layer = root.child("layer")
    assert layer is not None
    sheet_file = "demo.kicad_sch" if sheet_name == "/" else "channel.kicad_sch"
    placement = (
        f'\n\t(uuid "{uid(reference + "-footprint")}")\n\t(at {at[0]} {at[1]})'
        f'\n\t(path "{path}")\n\t(sheetname "{sheet_name}")\n\t(sheetfile "{sheet_file}")'
    )
    edits.append((layer.end, layer.end, placement))
    for name, value in (("Reference", reference), ("Value", part.value)):
        atom = root.property(name)
        assert atom is not None
        edits.append((atom.start, atom.end, sexpr.quote(value)))
    placed = sexpr.splice(text, edits)
    return "".join("\t" + line + "\n" for line in placed.rstrip("\n").split("\n"))


BOARD_HEADER = """(kicad_pcb
\t(version 20241229)
\t(generator "pcbnew")
\t(generator_version "9.0")
\t(general (thickness 1.6) (legacy_teardrops no))
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings")
\t\t(19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1")
\t\t(23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user)
\t\t(27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(33 "B.Fab" user)
\t)
\t(setup (pad_to_mask_clearance 0))
\t(net 0 "")
\t(gr_rect (start 90 70) (end 165 120) (stroke (width 0.1) (type default)) (fill no)
\t\t(layer "Edge.Cuts") (uuid "@OUTLINE@"))
"""


def write_schematics() -> None:
    root_uuid = uid("root")
    root_path = f"/{root_uuid}"
    symbols = "".join(placed_symbol(part, [(root_path, part.reference)]) for part in ROOT_PARTS)
    sheets = "".join(
        f"\t(sheet (at {at[0]} {at[1]}) (size 30 20)"
        " (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)"
        f' (uuid "{uid(name)}")\n'
        f'\t\t(property "Sheetname" "{name}" (at {at[0]} {at[1] - 1} 0)'
        " (effects (font (size 1.27 1.27)) (justify left bottom)))\n"
        f'\t\t(property "Sheetfile" "channel.kicad_sch" (at {at[0]} {at[1] + 21} 0)'
        " (effects (font (size 1.27 1.27)) (justify left top)))\n"
        f'\t\t(instances (project "demo" (path "{root_path}" (page "{index + 2}"))))\n'
        "\t)\n"
        for index, (name, at) in enumerate(SHEETS)
    )
    write(
        PROJECT / "demo.kicad_sch",
        schematic(
            root_uuid, ROOT_PARTS, symbols + sheets + '\t(sheet_instances (path "/" (page "1")))\n'
        ),
    )
    channel_symbols = "".join(
        placed_symbol(
            part,
            [
                (f"{root_path}/{uid(name)}", part.sheet_refs[index])
                for index, (name, _) in enumerate(SHEETS)
            ],
        )
        for part in CHANNEL_PARTS
    )
    write(PROJECT / "channel.kicad_sch", schematic(uid("channel"), CHANNEL_PARTS, channel_symbols))


def schematic(sheet_uuid: str, parts: list[Placed], body: str) -> str:
    cache = "".join(
        cached_symbol(lib_id) + "\n" for lib_id in sorted({part.lib_id for part in parts})
    )
    return (
        f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "10.0")'
        f' (uuid "{sheet_uuid}") (paper "A4")\n'
        f"\t(lib_symbols\n{cache}\t)\n{body})\n"
    )


def cached_symbol(lib_id: str) -> str:
    if lib_id.startswith("Device:"):
        device = (KICAD / "stock/symbols/Device.kicad_sym").read_text()
        node = next(
            node
            for node in sexpr.parse(device).children("symbol")
            if name_atom(node).value == lib_id.partition(":")[2]
        )
        block = sexpr.line_block(device, node)
        block = block.replace(f'(symbol "{name_atom(node).value}"', f'(symbol "{lib_id}"', 1)
        return "\n".join("\t" + line for line in block.split("\n"))
    spec = SPECS[lib_id]
    parent = SPECS[f"{lib_id.partition(':')[0]}:{spec.extends}"] if spec.extends else spec
    return symbol_text(spec, lib_id, 2, parent)


def placed_symbol(part: Placed, instances: list[tuple[str, str]]) -> str:
    spec = SPECS.get(part.lib_id)
    datasheet = spec.datasheet if spec else ""
    description = spec.description if spec else ""
    if spec is None:
        pins = ["1", "2"]
    else:
        shape = SPECS[f"{part.lib_id.partition(':')[0]}:{spec.extends}"] if spec.extends else spec
        pins = [pin.number for pin in shape.pins]
    x, y = part.at
    properties = "".join(
        f'\t\t(property "{name}" "{value}" (at {x} {y + offset} 0){" (hide yes)" if hidden else ""}'
        " (effects (font (size 1.27 1.27))))\n"
        for name, value, offset, hidden in (
            ("Reference", part.reference, -6, False),
            ("Value", part.value, 6, False),
            ("Footprint", part.footprint, 0, True),
            ("Datasheet", datasheet, 0, True),
            ("Description", description, 0, True),
        )
    )
    pin_lines = "".join(
        f'\t\t(pin "{number}" (uuid "{uid(part.reference + "-pin-" + number)}"))\n'
        for number in pins
    )
    paths = "".join(
        f'(path "{path}" (reference "{reference}") (unit 1))' for path, reference in instances
    )
    return (
        f'\t(symbol (lib_id "{part.lib_id}") (at {x} {y} 0) (unit 1)'
        " (exclude_from_sim no) (in_bom yes)"
        f' (on_board yes) (dnp no) (uuid "{uid(part.reference)}")\n'
        f"{properties}{pin_lines}"
        f'\t\t(instances (project "demo" {paths}))\n'
        "\t)\n"
    )


if __name__ == "__main__":
    main()
