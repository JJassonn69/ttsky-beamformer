#!/usr/bin/env python3
"""Generate an obstacle-aware OpenROAD job for 41 controller/analog handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET2,
    MET3,
    MET4,
    clipped_rectangle,
    flatten_orthogonal_rectangles,
    parse_gds,
    union_area,
)


DBU = 1000
LAYER_TO_GDS = {"met2": MET2, "met3": MET3, "met4": MET4}
GDS_TO_LAYER = {value: key for key, value in LAYER_TO_GDS.items()}
TRACK_PITCH = {
    "li1": (0.46, 0.34),
    "met1": (0.34, 0.34),
    "met2": (0.46, 0.46),
    "met3": (0.68, 0.68),
    "met4": (0.92, 0.92),
}
TRACK_OFFSET = {
    "li1": (0.23, 0.17),
    "met1": (0.17, 0.17),
    "met2": (0.23, 0.23),
    "met3": (0.34, 0.34),
    "met4": (0.46, 0.46),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_hash(path: Path, expected: str, name: str) -> None:
    observed = sha256(path)
    if observed != expected:
        raise ValueError(f"{name} hash differs: expected {expected}, got {observed}")


def q(value: float) -> int:
    return round(float(value) * DBU)


def tcl_path(path: Path) -> str:
    value = str(path.resolve())
    if "{" in value or "}" in value:
        raise ValueError(f"Tcl path contains a brace: {value}")
    return "{" + value + "}"


def track_values(layer: str, axis: int, lower_global: float, extent: float) -> list[float]:
    pitch = TRACK_PITCH[layer][axis]
    first = (TRACK_OFFSET[layer][axis] - lower_global) % pitch
    count = max(1, math.floor((extent - first) / pitch) + 1)
    return [round(first + index * pitch, 6) for index in range(count)]


def rect_intersection(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    return clipped_rectangle(first, second)


def subtract_rectangle(rectangle: tuple[float, float, float, float], cut: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    overlap = rect_intersection(rectangle, cut)
    if overlap is None:
        return [rectangle]
    x0, y0, x1, y1 = rectangle
    cx0, cy0, cx1, cy1 = overlap
    pieces = [
        (x0, y0, cx0, y1),
        (cx1, y0, x1, y1),
        (cx0, y0, cx1, cy0),
        (cx0, cy1, cx1, y1),
    ]
    return [piece for piece in pieces if piece[0] < piece[2] and piece[1] < piece[3]]


def covered(rectangle: tuple[float, float, float, float], conductors: list[tuple[float, float, float, float]]) -> bool:
    intersections = [
        item for conductor in conductors
        if (item := clipped_rectangle(conductor, rectangle)) is not None
    ]
    expected = (rectangle[2] - rectangle[0]) * (rectangle[3] - rectangle[1])
    return abs(union_area(intersections) - expected) < 1e-8


def controller_pin(name: str, manifest: dict[str, Any], access: dict[str, Any]) -> dict[str, Any]:
    record = manifest["boundary_pins"][name]
    if record["edge"] != "west" or record["layer"] != "met3":
        raise ValueError(f"{name}: controller handoff is not a west-edge M3 pin")
    ox, oy = map(float, manifest["coordinate_offset_um"])
    px, py = map(float, record["point_um"])
    edge = ox + px
    center_y = oy + py
    width = float(access["controller_m3_edge_width_um"])
    half_height = float(access["pin_height_um"]) / 2.0
    return {
        "role": "controller_source",
        "logical": name,
        "layer": "met3",
        "rect_um": [edge, center_y - half_height, edge + width, center_y + half_height],
        "exit_edge": "west",
    }


def outer_edge_pin(
    name: str,
    layer: str,
    point: list[float],
    source_rectangles: dict[str, list[tuple[float, float, float, float]]],
    width: float,
    height: float,
    role: str,
    east_extension: float = 0.0,
    line_end_halo: float = 0.0,
) -> dict[str, Any]:
    px, py = map(float, point)
    containing = [
        rectangle for rectangle in source_rectangles[layer]
        if rectangle[0] - 1e-9 <= px <= rectangle[2] + 1e-9
        and rectangle[1] - 1e-9 <= py <= rectangle[3] + 1e-9
    ]
    if not containing:
        raise ValueError(f"{name}: no {layer} conductor contains {point}")
    edge = max(rectangle[2] for rectangle in containing)
    half_height = height / 2.0
    pin = (edge - width, py - half_height, edge, py + half_height)
    if not covered(pin, source_rectangles[layer]):
        raise ValueError(f"{name}: east-edge pin is not fully covered by source metal")
    edge_rectangles = [
        rectangle for rectangle in containing
        if abs(rectangle[2] - edge) < 1e-9
        and rectangle[0] <= edge - width + 1e-9
    ]
    blockage_window = (
        edge - width,
        min(rectangle[1] for rectangle in edge_rectangles),
        edge,
        max(rectangle[3] for rectangle in edge_rectangles),
    )
    result = {
        "role": role,
        "logical": name,
        "layer": layer,
        "rect_um": list(pin),
        "blockage_window_um": list(blockage_window),
        "exit_edge": "east",
    }
    if east_extension > 0.0 or line_end_halo > 0.0:
        if east_extension < 0.30 or line_end_halo < 0.30:
            raise ValueError(f"{name}: generated access pad lacks 0.30 um halo")
        source_y0 = min(rectangle[1] for rectangle in edge_rectangles)
        source_y1 = max(rectangle[3] for rectangle in edge_rectangles)
        result.update({
            "rect_um": [
                edge - width,
                source_y0 - line_end_halo,
                edge + east_extension,
                source_y1 + line_end_halo,
            ],
            "source_overlap_rect_um": [edge - width, source_y0, edge, source_y1],
            "generated_access_pad": True,
            "generated_access_pad_reason": (
                "symmetric M4 terminal with foundry-rule line-end halo"
            ),
        })
    return result


def endpoint_contract(plan: dict[str, Any], source_rectangles: dict[str, list[tuple[float, float, float, float]]]) -> list[dict[str, Any]]:
    sources = plan["endpoint_sources"]
    manifest = json.loads((ROOT / sources["controller_boundary_manifest"]).read_text(encoding="utf-8"))
    placement = json.loads((ROOT / sources["four_channel_placement"]).read_text(encoding="utf-8"))
    phases = json.loads((ROOT / sources["phase_distribution"]).read_text(encoding="utf-8"))
    access = plan["pin_access"]
    m3_width = float(access["analog_m3_edge_width_um"])
    m4_width = float(access["phase_m4_edge_width_um"])
    height = float(access["pin_height_um"])
    channels = {int(item["channel"]): item for item in placement["instances"]}
    nets: list[dict[str, Any]] = []

    for source_name, phase_name in plan["phase_mapping"].items():
        tree = phases["trees"][phase_name]
        leaf = tree["m3_track_points_um"][-1]
        target_point = [float(leaf[0]), float(tree["leaf_y_um"])]
        nets.append({
            "net": source_name,
            "route_class": "phase",
            "source": controller_pin(source_name, manifest, access),
            "targets": [outer_edge_pin(
                phase_name, "met4", target_point, source_rectangles,
                m4_width, height, "phase_tree_target",
                float(access["phase_access_east_extension_um"]),
                float(access["phase_access_line_end_halo_um"]),
            )],
            "target_logical_nets": [phase_name],
        })

    for channel in reversed(range(4)):
        instance = channels[channel]
        for group in range(4):
            for bit in range(2):
                index = 8 * channel + 2 * group + bit
                source_name = f"group_codes[{index}]"
                port_name = f"group{group}_bit{bit}"
                target = instance["ports"][port_name]
                nets.append({
                    "net": source_name,
                    "route_class": "group_code",
                    "source": controller_pin(source_name, manifest, access),
                    "targets": [outer_edge_pin(
                        f"channel{channel}.{port_name}", "met3", target["at_um"],
                        source_rectangles, m3_width, height, "channel_code_target",
                    )],
                    "target_logical_nets": [f"XCHANNEL{channel}/{port_name}"],
                })

    for channel in reversed(range(4)):
        source_name = f"channel_bias_enable[{channel}]"
        target = channels[channel]["ports"]["channel_enable"]
        nets.append({
            "net": source_name,
            "route_class": "channel_bias",
            "source": controller_pin(source_name, manifest, access),
            "targets": [outer_edge_pin(
                f"channel{channel}.channel_enable", "met3", target["at_um"],
                source_rectangles, m3_width, height, "channel_enable_target",
            )],
            "target_logical_nets": [f"XCHANNEL{channel}/channel_enable"],
        })

    blank_targets = []
    blank_logical = []
    for channel in reversed(range(4)):
        target = channels[channel]["ports"]["mixers_blank"]
        blank_targets.append(outer_edge_pin(
            f"channel{channel}.mixers_blank", "met3", target["at_um"],
            source_rectangles, m3_width, height, "channel_blank_target",
        ))
        blank_logical.append(f"XCHANNEL{channel}/mixers_blank")
    nets.append({
        "net": "mixers_blank",
        "route_class": "blanking",
        "source": controller_pin("mixers_blank", manifest, access),
        "targets": blank_targets,
        "target_logical_nets": blank_logical,
    })
    return nets


def build_def(plan: dict[str, Any], nets: list[dict[str, Any]], source_rectangles: dict[str, list[tuple[float, float, float, float]]]) -> tuple[str, dict[str, Any]]:
    x0, y0, x1, y1 = map(float, plan["route_region_bbox_um"])
    width, height = x1 - x0, y1 - y0
    endpoints = [endpoint for net in nets for endpoint in [net["source"], *net["targets"]]]
    windows = {
        layer: [
            tuple(map(float, item.get("blockage_window_um", item["rect_um"])))
            for item in endpoints if item["layer"] == layer
        ]
        for layer in plan["routing_layers"]
    }
    for endpoint in endpoints:
        rectangle = tuple(map(float, endpoint.get(
            "source_overlap_rect_um", endpoint["rect_um"]
        )))
        if not covered(rectangle, source_rectangles[endpoint["layer"]]):
            raise ValueError(f"{endpoint['logical']}: route pin is not covered by source metal")

    blockages: list[dict[str, Any]] = []
    region = (x0, y0, x1, y1)
    for layer in plan["routing_layers"]:
        for source_rectangle in source_rectangles[layer]:
            clipped = clipped_rectangle(source_rectangle, region)
            if clipped is None:
                continue
            pieces = [clipped]
            for window in windows[layer]:
                next_pieces = []
                for piece in pieces:
                    next_pieces.extend(subtract_rectangle(piece, window))
                pieces = next_pieces
            for piece in pieces:
                local = [piece[0] - x0, piece[1] - y0, piece[2] - x0, piece[3] - y0]
                blockages.append({"layer": layer, "rect_um": local})

    lines = [
        "VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
        "DESIGN v3_control_analog_handoffs ;", "UNITS DISTANCE MICRONS 1000 ;",
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
    lines.append("COMPONENTS 0 ;")
    lines.append("END COMPONENTS")
    lines.append(f"BLOCKAGES {len(blockages)} ;")
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
            direction = "OUTPUT" if endpoint_index == 0 else "INPUT"
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
        net_id = f"N{net_index:03d}"
        lines.append(f"- {net_id}")
        for endpoint_index in range(1 + len(net["targets"])):
            lines.append(f"  ( PIN P{net_index:03d}_{endpoint_index} )")
        lines.append("  + USE SIGNAL ;")
    lines.extend(("END NETS", "END DESIGN", ""))
    return "\n".join(lines), {
        "schema_version": 1,
        "status": "generated",
        "scope": "41 controller outputs to frozen analog channel and phase-tree endpoints",
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
        "# Obstacle-aware V3 controller-to-analog top-level handoff route",
        f"set_thread_count {threads}",
        f"read_lef {tcl_path(technology_lef)}",
        f"read_def {tcl_path(workdir / 'input.def')}",
        "set_routing_layers -signal met2-met4 -clock met2-met4",
        "set_global_routing_layer_adjustment met2 0.25",
        "set_global_routing_layer_adjustment met3 0.15",
        "set_global_routing_layer_adjustment met4 0.10",
        f"global_route -guide_file {tcl_path(workdir / 'route.guide')} "
        f"-congestion_iterations 180 -congestion_report_file {tcl_path(workdir / 'congestion.rpt')} -verbose",
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
        f"write_db {tcl_path(workdir / 'routed.odb')}",
        "exit", "",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_analog_handoff_plan.json",
    )
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/openroad",
    )
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be in [1, 32]")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    source = ROOT / plan["source_checkpoint"]["gds"]
    require_hash(source, plan["source_checkpoint"]["sha256"], "powered-controller GDS")
    gate = ROOT / plan["source_checkpoint"]["physical_gate"]
    require_hash(gate, plan["source_checkpoint"]["physical_gate_sha256"], "powered-controller gate")
    for path_key, hash_key, label in (
        ("controller_boundary_manifest", "controller_boundary_manifest_sha256", "controller boundary manifest"),
        ("four_channel_placement", "four_channel_placement_sha256", "four-channel placement"),
        ("phase_distribution", "phase_distribution_sha256", "phase distribution"),
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
    nets = endpoint_contract(plan, source_rectangles)
    if len(nets) != int(plan["expected_net_count"]):
        raise ValueError("controller/analog handoff net count differs from plan")
    text, report = build_def(plan, nets, source_rectangles)
    if report["pin_count"] != int(plan["expected_pin_count"]):
        raise ValueError("controller/analog handoff pin count differs from plan")
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        build_route_tcl(args.technology_lef, args.workdir, args.threads),
        encoding="utf-8",
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
