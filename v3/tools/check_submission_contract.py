#!/usr/bin/env python3
"""Mirror the non-DRC TinyTapeout checks on the exact packaged V3 GDS.

The official action remains the release authority.  This local gate prevents
avoidable CI-only failures by checking the wrapper contract that electrical
DRC cannot infer: top/boundary, legal artifact-specific layers, exact ports,
power declarations, analog-pin adjacency, and readable Verilog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_gds_flat_rules import (  # noqa: E402
    MET4,
    VIA3,
    flatten_orthogonal_rectangles,
    parse_gds,
)
from template_pins import submission_pins  # noqa: E402


TOP = "tt_um_jjassonn69_beamformer"
EXPECTED_SIZE_NM = (334_880, 225_760)
EXPECTED_ANALOG_PINS = 6
PIN_LAYER = (71, 16)
MET4_TEXT = (71, 5)
PRBOUNDARY = (235, 4)
FORBIDDEN = {(72, 20), (72, 16), (72, 5)}

# Exact layer population inherited from the independently clean frozen source,
# plus the official met4 pin-purpose and full-die prBoundary wrapper records.
# Freezing this set is stricter than accepting every possible SKY130 layer: an
# accidental new datatype must be reviewed even if the PDK knows its name.
EXPECTED_LAYER_PAIRS = {
    (64, 5), (64, 16), (64, 20), (64, 59),
    (65, 20), (65, 44),
    (66, 13), (66, 20), (66, 44),
    (67, 5), (67, 16), (67, 20), (67, 44),
    (68, 5), (68, 16), (68, 20), (68, 44),
    (69, 5), (69, 16), (69, 20), (69, 44),
    (70, 5), (70, 16), (70, 20), (70, 44),
    (71, 5), (71, 16), (71, 20),
    (78, 44), (79, 20), (81, 4), (83, 44), (86, 20),
    (89, 44), (93, 44), (94, 20), (95, 20),
    (122, 16), (235, 4), (236, 0),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_klayout(value: Path | None) -> Path:
    if value is not None:
        return value
    discovered = shutil.which("klayout")
    if discovered:
        return Path(discovered)
    mac = Path("/Applications/KLayout/klayout.app/Contents/MacOS/klayout")
    if mac.is_file():
        return mac
    raise SystemExit("KLayout was not found; pass --klayout")


def raw_layer_pairs(path: Path) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    raw = path.read_bytes()
    offset = 0
    current_layer: int | None = None
    in_element = False
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError(f"truncated GDS record at byte {offset}")
        length, record_type, _data_type = struct.unpack(">HBB", raw[offset : offset + 4])
        if length < 4 or offset + length > len(raw):
            raise ValueError(f"invalid GDS record at byte {offset}")
        data = raw[offset + 4 : offset + length]
        offset += length
        if record_type in {0x08, 0x09, 0x0C, 0x15, 0x2D}:  # boundary/path/text/node/box
            in_element = True
            current_layer = None
        elif in_element and record_type == 0x0D and len(data) >= 2:
            current_layer = struct.unpack(">h", data[:2])[0]
        elif in_element and record_type in {0x0E, 0x16, 0x2E} and current_layer is not None:
            result.add((current_layer, struct.unpack(">h", data[:2])[0]))
        elif record_type == 0x11:
            in_element = False
            current_layer = None
    return result


def parse_lef_ports(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    ports: dict[str, dict[str, Any]] = {}
    pattern = re.compile(
        r"^\s*PIN (\S+)\s*$([\s\S]*?)^\s*END \1\s*$", re.MULTILINE
    )
    for name, body in pattern.findall(text):
        direction = re.search(r"^\s*DIRECTION (\S+) ;", body, re.MULTILINE)
        use = re.search(r"^\s*USE (\S+) ;", body, re.MULTILINE)
        layer = re.search(r"^\s*LAYER (\S+) ;", body, re.MULTILINE)
        rect = re.search(
            r"^\s*RECT (-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+) ;",
            body,
            re.MULTILINE,
        )
        if not all((direction, use, layer, rect)):
            raise ValueError(f"incomplete LEF port {name}")
        ports[name] = {
            "direction": direction.group(1),
            "use": use.group(1),
            "layer": layer.group(1),
            "rect_nm": tuple(round(float(value) * 1000) for value in rect.groups()),
        }
    return ports


def intersection_area(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def analog_adjacency(gds: Path) -> dict[str, bool]:
    structures, database_um = parse_gds(gds)
    flat = flatten_orthogonal_rectangles(
        structures, TOP, database_um, {MET4, VIA3}
    )
    result: dict[str, bool] = {}
    for pin in range(8):
        left = 151.81 - 19.32 * pin
        pin_rect = (left, 0.0, left + 0.9, 1.0)
        outer = (left - 0.5, -0.5, left + 1.4, 1.5)
        inner = (left - 0.1, -0.1, left + 1.0, 1.1)
        metal_connected = any(
            intersection_area(rect, outer) - intersection_area(rect, inner) > 1e-9
            for rect in flat[MET4]
        )
        via_connected = any(
            intersection_area(rect, pin_rect) > 1e-9 for rect in flat[VIA3]
        )
        result[f"ua[{pin}]"] = metal_connected or via_connected
    return result


def marker_count(path: Path) -> int:
    return len(ET.parse(path).getroot().findall(".//items/item"))


def run_command(command: list[str], log: Path) -> int:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result.returncode


def check(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    candidate_hash = sha256(args.gds)
    package = json.loads(args.package_report.read_text(encoding="utf-8"))
    if package.get("submission_sha256") != candidate_hash:
        errors.append("packaging report is stale for the candidate GDS")

    klayout = resolve_klayout(args.klayout)
    probe_path = args.output_dir / "klayout_structure.json"
    probe_log = args.output_dir / "klayout_structure.log"
    probe_exit = run_command(
        [
            str(klayout), "-b", "-r", str(ROOT / "v3/layout/probe_submission_contract.rb"),
            "-rd", f"input={args.gds.resolve()}", "-rd", f"top_cell={TOP}",
            "-rd", f"output={probe_path.resolve()}",
        ],
        probe_log,
    )
    if probe_exit != 0 or not probe_path.is_file():
        errors.append("KLayout structural probe failed")
        probe: dict[str, Any] = {}
    else:
        probe = json.loads(probe_path.read_text(encoding="utf-8"))

    expected_bbox_dbu = [0, 0, *EXPECTED_SIZE_NM]
    if probe.get("top_cells") != [TOP]:
        errors.append(f"GDS top-level is not uniquely {TOP}: {probe.get('top_cells')}")
    if probe.get("top_bbox_dbu") != expected_bbox_dbu:
        errors.append(f"top bbox differs from the official template: {probe.get('top_bbox_dbu')}")
    if probe.get("prboundary_bbox_dbu") != expected_bbox_dbu:
        errors.append(f"prBoundary bbox differs from the official template: {probe.get('prboundary_bbox_dbu')}")
    invalid_names = [name for name in probe.get("cell_names", []) if "#" in name or "/" in name]
    if invalid_names:
        errors.append(f"invalid GDS cell names: {invalid_names}")

    layers = raw_layer_pairs(args.gds)
    if layers != EXPECTED_LAYER_PAIRS:
        errors.append(
            f"candidate layer population differs; missing={sorted(EXPECTED_LAYER_PAIRS-layers)}, "
            f"extra={sorted(layers-EXPECTED_LAYER_PAIRS)}"
        )
    if layers & FORBIDDEN:
        errors.append(f"forbidden met5 layers present: {sorted(layers & FORBIDDEN)}")

    width_nm, height_nm, pins = submission_pins(args.template_def)
    if (width_nm, height_nm) != EXPECTED_SIZE_NM or len(pins) != 53:
        errors.append("pinned template size/pin count differs")
    lef_ports = parse_lef_ports(args.lef)
    expected_ports = {
        pin.name: {
            "direction": pin.direction,
            "use": pin.use,
            "layer": pin.layer,
            "rect_nm": pin.rect_nm,
        }
        for pin in pins
    }
    if lef_ports != expected_ports:
        errors.append("LEF ports are not exactly equal to the pinned template plus power ports")

    structures, database_um = parse_gds(args.gds)
    top = structures.get(TOP)
    if top is None:
        errors.append("packaged top missing from dependency-free GDS parser")
        top_pin_rects: list[tuple[int, int, int, int]] = []
        top_boundaries: list[tuple[int, int, int, int]] = []
    else:
        def rect_nm(points: list[tuple[int, int]]) -> tuple[int, int, int, int]:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return tuple(round(value * database_um * 1000) for value in (min(xs), min(ys), max(xs), max(ys)))

        top_pin_rects = [rect_nm(poly) for layer, poly in top.polygons if layer == PIN_LAYER]
        top_boundaries = [rect_nm(poly) for layer, poly in top.polygons if layer == PRBOUNDARY]
    if len(top_pin_rects) != 53 or set(top_pin_rects) != {pin.rect_nm for pin in pins}:
        errors.append("GDS met4 pin-purpose polygons differ from the exact 53 official ports")
    if top_boundaries != [(0, 0, *EXPECTED_SIZE_NM)]:
        errors.append("top does not contain exactly one full-die prBoundary polygon")

    adjacency = analog_adjacency(args.gds)
    expected_adjacency = {f"ua[{index}]": index < EXPECTED_ANALOG_PINS for index in range(8)}
    if adjacency != expected_adjacency:
        errors.append(f"analog-pin adjacency differs: {adjacency}")

    verilog_text = args.verilog.read_text(encoding="utf-8")
    if not re.search(rf"\bmodule\s+{re.escape(TOP)}\b", verilog_text):
        errors.append("Verilog top-module declaration differs")
    if "VAPWR" in re.sub(r"//.*", "", verilog_text):
        errors.append("Verilog exposes VAPWR while uses_vapwr is false")
    if not all(name in verilog_text for name in ("VDPWR", "VGND")):
        errors.append("Verilog power declarations are incomplete")

    iverilog_log = args.output_dir / "iverilog.log"
    iverilog_output = args.output_dir / "project_syntax.vvp"
    iverilog_exit = run_command(
        ["iverilog", "-g2012", "-s", TOP, "-o", str(iverilog_output), str(args.verilog)],
        iverilog_log,
    )
    if iverilog_exit != 0:
        errors.append("iverilog could not read the TinyTapeout boundary module")

    nwell_report = args.output_dir / "nwell_urpm.xml"
    nwell_log = args.output_dir / "nwell_urpm.log"
    nwell_exit = run_command(
        [
            str(klayout), "-b", "-r", str(args.support_tools / "precheck/tech-files/nwell_urpm.drc"),
            "-rd", f"input={args.gds.resolve()}", "-rd", f"top_cell={TOP}",
            "-rd", "thr=1", "-rd", f"report={nwell_report.resolve()}",
        ],
        nwell_log,
    )
    nwell_markers = marker_count(nwell_report) if nwell_report.is_file() else None
    if nwell_exit != 0 or nwell_markers != 0:
        errors.append(f"urpm/nwell check failed: exit={nwell_exit}, markers={nwell_markers}")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "local mirror of non-DRC TinyTapeout SKY130 wrapper checks on the exact packaged V3 artifact",
        "errors": errors,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": candidate_hash,
        "checks": {
            "unique_top": probe.get("top_cells") == [TOP],
            "top_bbox_dbu": probe.get("top_bbox_dbu"),
            "prboundary_bbox_dbu": probe.get("prboundary_bbox_dbu"),
            "prboundary_polygon_count_recursive": probe.get("prboundary_polygon_count_recursive"),
            "invalid_cell_names": invalid_names,
            "exact_artifact_layer_population": layers == EXPECTED_LAYER_PAIRS,
            "layer_pairs": [list(pair) for pair in sorted(layers)],
            "forbidden_layer_hits": [list(pair) for pair in sorted(layers & FORBIDDEN)],
            "exact_lef_ports": lef_ports == expected_ports,
            "exact_gds_pin_purpose_shapes": len(top_pin_rects) == 53 and set(top_pin_rects) == {pin.rect_nm for pin in pins},
            "analog_pin_adjacency": adjacency,
            "expected_analog_pin_adjacency": expected_adjacency,
            "verilog_syntax_exit": iverilog_exit,
            "nwell_urpm_exit": nwell_exit,
            "nwell_urpm_markers": nwell_markers,
        },
        "artifact_sha256": {
            "gds": candidate_hash,
            "package_report": sha256(args.package_report),
            "template_def": sha256(args.template_def),
            "lef": sha256(args.lef),
            "verilog": sha256(args.verilog),
            "klayout_probe": sha256(probe_path) if probe_path.is_file() else None,
            "nwell_urpm_report": sha256(nwell_report) if nwell_report.is_file() else None,
            "checker": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/submission"
    parser.add_argument("--gds", type=Path, default=base / f"{TOP}.gds")
    parser.add_argument("--package-report", type=Path, default=base / "gds_packaging.json")
    parser.add_argument("--template-def", type=Path, default=ROOT / "build/v2/tt_analog_2x2.def")
    parser.add_argument("--lef", type=Path, default=ROOT / f"lef/{TOP}.lef")
    parser.add_argument("--verilog", type=Path, default=ROOT / "src/project.v")
    parser.add_argument("--support-tools", type=Path, default=Path("/Users/ganeshpanth/tt-support-tools-pinned"))
    parser.add_argument("--klayout", type=Path)
    parser.add_argument("--output-dir", type=Path, default=base / "official_contract")
    parser.add_argument("--output", type=Path, default=base / "official_contract.json")
    args = parser.parse_args()
    report = check(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
