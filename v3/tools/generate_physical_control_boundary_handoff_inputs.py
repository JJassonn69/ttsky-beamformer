#!/usr/bin/env python3
"""Generate the obstacle-aware OpenROAD job for 14 TinyTapeout input handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET2,
    MET3,
    MET4,
    clipped_rectangle,
    flatten_orthogonal_rectangles,
    parse_gds,
)
from template_pins import parse_template  # noqa: E402
from generate_physical_control_analog_handoff_inputs import (  # noqa: E402
    DBU,
    GDS_TO_LAYER,
    LAYER_TO_GDS,
    TRACK_PITCH,
    q,
    require_hash,
    subtract_rectangle,
    tcl_path,
    track_values,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def controller_endpoint(name: str, manifest: dict[str, Any]) -> dict[str, Any]:
    record = manifest["boundary_pins"][name]
    if record["direction"] != "INPUT" or record["edge"] != "north":
        raise ValueError(f"{name}: expected a north-edge controller input")
    if record["layer"] != "met2":
        raise ValueError(f"{name}: expected controller access on M2")
    ox, oy = map(float, manifest["coordinate_offset_um"])
    px, py = map(float, record["point_um"])
    rx0, ry0, rx1, ry1 = map(float, record["rect_um"])
    return {
        "role": "controller_input",
        "logical": name,
        "layer": "met2",
        "rect_um": [ox + px + rx0, oy + py + ry0, ox + px + rx1, oy + py + ry1],
        "exit_edge": "north",
        "requires_source_coverage": True,
    }


def template_endpoint(pin_name: str, template_pins: dict[str, Any]) -> dict[str, Any]:
    pin = template_pins[pin_name]
    if pin.layer != "met4" or pin.direction != "INPUT":
        raise ValueError(f"{pin_name}: expected an official M4 input pin")
    return {
        "role": "tinytapeout_input_pin",
        "logical": pin_name,
        "layer": "met4",
        "rect_um": [value / 1000.0 for value in pin.rect_nm],
        "exit_edge": "north",
        "requires_source_coverage": False,
    }


def endpoint_contract(plan: dict[str, Any]) -> list[dict[str, Any]]:
    sources = plan["endpoint_sources"]
    manifest = json.loads(
        (ROOT / sources["controller_boundary_manifest"]).read_text(encoding="utf-8")
    )
    _width, _height, parsed = parse_template(ROOT / sources["tinytapeout_template_def"])
    template = {pin.name: pin for pin in parsed}
    nets = []
    for logical, template_pin in plan["pin_mapping"].items():
        source = controller_endpoint(logical, manifest)
        target = template_endpoint(template_pin, template)
        nets.append({
            "net": logical,
            "route_class": manifest["boundary_pins"][logical]["routing_class"],
            "source": source,
            "targets": [target],
            "target_logical_nets": [template_pin],
        })
    return nets


def point_covered(
    rectangle: tuple[float, float, float, float],
    conductors: list[tuple[float, float, float, float]],
) -> bool:
    x0, y0, x1, y1 = rectangle
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return any(
        item[0] - 1e-9 <= cx <= item[2] + 1e-9
        and item[1] - 1e-9 <= cy <= item[3] + 1e-9
        for item in conductors
    )


def build_def(
    plan: dict[str, Any],
    nets: list[dict[str, Any]],
    source_rectangles: dict[str, list[tuple[float, float, float, float]]],
) -> tuple[str, dict[str, Any]]:
    x0, y0, x1, y1 = map(float, plan["route_region_bbox_um"])
    width, height = x1 - x0, y1 - y0
    endpoints = [endpoint for net in nets for endpoint in [net["source"], *net["targets"]]]
    source_windows = {
        layer: [
            tuple(map(float, endpoint["rect_um"]))
            for endpoint in endpoints
            if endpoint["layer"] == layer and endpoint["requires_source_coverage"]
        ]
        for layer in plan["routing_layers"]
    }
    for endpoint in endpoints:
        rectangle = tuple(map(float, endpoint["rect_um"]))
        if endpoint["requires_source_coverage"] and not point_covered(
            rectangle, source_rectangles[endpoint["layer"]]
        ):
            raise ValueError(f"{endpoint['logical']}: source access is not on inherited metal")
        if not (x0 <= rectangle[0] < rectangle[2] <= x1 and y0 <= rectangle[1] < rectangle[3] <= y1):
            raise ValueError(f"{endpoint['logical']}: endpoint leaves the route region")

    blockages: list[dict[str, Any]] = []
    region = (x0, y0, x1, y1)
    for layer in plan["routing_layers"]:
        for source_rectangle in source_rectangles[layer]:
            clipped = clipped_rectangle(source_rectangle, region)
            if clipped is None:
                continue
            pieces = [clipped]
            for window in source_windows[layer]:
                next_pieces = []
                for piece in pieces:
                    next_pieces.extend(subtract_rectangle(piece, window))
                pieces = next_pieces
            for piece in pieces:
                blockages.append({
                    "layer": layer,
                    "rect_um": [
                        piece[0] - x0, piece[1] - y0,
                        piece[2] - x0, piece[3] - y0,
                    ],
                })

    lines = [
        "VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
        "DESIGN v3_control_boundary_handoffs ;", "UNITS DISTANCE MICRONS 1000 ;",
        f"DIEAREA ( 0 0 ) ( {q(width)} {q(height)} ) ;",
    ]
    for layer in TRACK_PITCH:
        for axis_index, (axis, extent, lower) in enumerate(
            (("X", width, x0), ("Y", height, y0))
        ):
            tracks = track_values(layer, axis_index, lower, extent)
            lines.append(
                f"TRACKS {axis} {q(tracks[0])} DO {len(tracks)} "
                f"STEP {q(TRACK_PITCH[layer][axis_index])} LAYER {layer} ;"
            )
    lines.extend(("COMPONENTS 0 ;", "END COMPONENTS", f"BLOCKAGES {len(blockages)} ;"))
    for blockage in blockages:
        bx0, by0, bx1, by1 = blockage["rect_um"]
        lines.extend((
            f"- LAYER {blockage['layer']}",
            f"  RECT ( {q(bx0)} {q(by0)} ) ( {q(bx1)} {q(by1)} ) ;",
        ))
    lines.append("END BLOCKAGES")

    pin_manifest: dict[str, dict[str, Any]] = {}
    net_manifest: dict[str, str] = {}
    pin_records: list[tuple[str, str, str, dict[str, Any]]] = []
    for net_index, net in enumerate(nets):
        net_id = f"N{net_index:03d}"
        net_manifest[net_id] = net["net"]
        for endpoint_index, endpoint in enumerate([net["source"], *net["targets"]]):
            pin_id = f"P{net_index:03d}_{endpoint_index}"
            direction = "INPUT" if endpoint_index == 0 else "OUTPUT"
            pin_records.append((pin_id, net_id, direction, endpoint))
            pin_manifest[pin_id] = endpoint
    lines.append(f"PINS {len(pin_records)} ;")
    for pin_id, net_id, direction, endpoint in pin_records:
        rx0, ry0, rx1, ry1 = map(float, endpoint["rect_um"])
        local = [rx0 - x0, ry0 - y0, rx1 - x0, ry1 - y0]
        lines.extend((
            f"- {pin_id} + NET {net_id} + DIRECTION {direction} + USE SIGNAL",
            "  + PORT",
            f"    + LAYER {endpoint['layer']} "
            f"( {q(local[0])} {q(local[1])} ) ( {q(local[2])} {q(local[3])} )",
            "  + PLACED ( 0 0 ) N ;",
        ))
    lines.append("END PINS")
    lines.append(f"NETS {len(nets)} ;")
    for net_index, net in enumerate(nets):
        lines.append(f"- N{net_index:03d}")
        for endpoint_index in range(1 + len(net["targets"])):
            lines.append(f"  ( PIN P{net_index:03d}_{endpoint_index} )")
        lines.append("  + USE SIGNAL ;")
    lines.extend(("END NETS", "END DESIGN", ""))
    return "\n".join(lines), {
        "schema_version": 1,
        "status": "generated",
        "scope": "14 controller inputs to exact TinyTapeout top-boundary pins",
        "coordinate_offset_um": [x0, y0],
        "diearea_um": [0.0, 0.0, width, height],
        "net_count": len(nets),
        "pin_count": len(pin_records),
        "blockage_count": len(blockages),
        "blockages_by_layer": {
            layer: sum(item["layer"] == layer for item in blockages)
            for layer in plan["routing_layers"]
        },
        "net_ids": net_manifest,
        "pins": pin_manifest,
        "nets": nets,
        "policy": plan["policy"],
    }


def build_route_tcl(technology_lef: Path, workdir: Path, threads: int) -> str:
    return "\n".join((
        "# V3 TinyTapeout controller-input boundary handoffs",
        f"set_thread_count {threads}",
        f"read_lef {tcl_path(technology_lef)}",
        f"read_def {tcl_path(workdir / 'input.def')}",
        "set_routing_layers -signal met2-met4 -clock met2-met4",
        "set_global_routing_layer_adjustment met2 0.20",
        "set_global_routing_layer_adjustment met3 0.10",
        "set_global_routing_layer_adjustment met4 0.05",
        f"global_route -guide_file {tcl_path(workdir / 'route.guide')} "
        f"-congestion_iterations 240 -congestion_report_file {tcl_path(workdir / 'congestion.rpt')} -verbose",
        "if {[catch {",
        f"  detailed_route -output_drc {tcl_path(workdir / 'detailed_route_drc.rpt')} "
        f"-output_guide_coverage {tcl_path(workdir / 'guide_coverage.csv')} "
        "-droute_end_iter 64 -bottom_routing_layer met2 -top_routing_layer met4 "
        "-clean_patches -verbose 1",
        "} detailed_route_error detailed_route_options]} {",
        "  puts stderr $detailed_route_error",
        "  puts stderr [dict get $detailed_route_options -errorinfo]",
        "  exit 1",
        "}",
        f"report_wire_length -net * -global_route -detailed_route -verbose "
        f"-file {tcl_path(workdir / 'wire_length.csv')}",
        f"write_def {tcl_path(workdir / 'routed.def')}",
        "exit", "",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_boundary_handoff_plan.json",
    )
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_boundary_handoffs/openroad",
    )
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be in [1, 32]")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    source = ROOT / plan["source_checkpoint"]["gds"]
    require_hash(source, plan["source_checkpoint"]["sha256"], "internal-handoff GDS")
    gate = ROOT / plan["source_checkpoint"]["physical_gate"]
    require_hash(gate, plan["source_checkpoint"]["physical_gate_sha256"], "internal-handoff gate")
    for path_key, hash_key, label in (
        ("controller_boundary_manifest", "controller_boundary_manifest_sha256", "controller manifest"),
        ("tinytapeout_template_def", "tinytapeout_template_def_sha256", "TinyTapeout template"),
    ):
        require_hash(ROOT / plan["endpoint_sources"][path_key], plan["endpoint_sources"][hash_key], label)
    structures, database_um = parse_gds(source)
    flattened = flatten_orthogonal_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um,
        {MET2, MET3, MET4},
    )
    source_rectangles = {
        GDS_TO_LAYER[layer]: rectangles for layer, rectangles in flattened.items()
    }
    nets = endpoint_contract(plan)
    if len(nets) != int(plan["expected_net_count"]):
        raise ValueError("controller-boundary net count differs from plan")
    text, report = build_def(plan, nets, source_rectangles)
    if report["pin_count"] != int(plan["expected_pin_count"]):
        raise ValueError("controller-boundary pin count differs from plan")
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        build_route_tcl(args.technology_lef, args.workdir, args.threads), encoding="utf-8"
    )
    report["provenance"] = {
        "plan": str(args.plan),
        "plan_sha256": sha256(args.plan),
        "technology_lef": str(args.technology_lef),
        "technology_lef_sha256": sha256(args.technology_lef),
        "source_gds": str(source),
        "source_gds_sha256": sha256(source),
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__)),
    }
    (args.workdir / "input_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in (
        "status", "net_count", "pin_count", "blockage_count", "blockages_by_layer",
    )}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
