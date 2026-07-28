#!/usr/bin/env python3
"""Generate the fixed-placement OpenROAD job for the shared V3 controller.

This gate intentionally routes only inside the controller rectangle.  Stable
M2/M3 boundary handoffs are created for every top-level port; short, reviewed
top-level trunks will connect those handoffs to the already-frozen analog and
TinyTapeout infrastructure in the following integration gate.  M4 is excluded
so that the balanced phase and output infrastructure retains an uncongested
upper routing layer.
"""

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
    MET1,
    MET2,
    MET3,
    clipped_rectangle,
    connected_components,
    flatten_orthogonal_rectangles,
    parse_gds,
)


DBU = 1000
ORIENTATIONS = {"R0": "N", "MX": "FS", "MY": "FN", "R180": "S"}
ROUTING_LAYERS = ("li1", "met1", "met2", "met3")
GDS_ROUTE_LAYERS = {MET1: "met1", MET2: "met2", MET3: "met3"}
TRACK_PITCHES = {
    "li1": (0.46, 0.34),
    "met1": (0.34, 0.34),
    "met2": (0.46, 0.46),
    "met3": (0.68, 0.68),
}
TRACK_OFFSETS = {
    "li1": (0.23, 0.17),
    "met1": (0.17, 0.17),
    "met2": (0.23, 0.23),
    "met3": (0.34, 0.34),
}


def planned_power_contact_obstructions(
    power_plan: dict[str, Any], region: list[float]
) -> list[dict[str, Any]]:
    """Reserve the exact M2/M3 landings for distributed row-power contacts.

    Power is a later physical gate, but it cannot be treated as an afterthought:
    allowing signals to occupy every upper-metal access point leaves long,
    resistive edge-fed M1 rails.  The selected quarter-span contacts cap the
    nominal rail distance to about 35 um.  These rectangles are the future
    via-stack landings; OpenROAD applies the foundry spacing rules around them.
    """

    x0, y0, x1, y1 = map(float, region)
    configured = list(map(float, power_plan["distributed_contact_columns_um"]))
    if len(configured) != 2 or configured != sorted(configured):
        raise ValueError("controller power plan must reserve two ordered contact columns")
    result: list[dict[str, Any]] = []
    row_count = int(power_plan["controller_region"]["row_count"])
    row_height = float(power_plan["controller_region"]["row_height_um"])
    planned_region = list(map(float, power_plan["controller_region"]["bbox_um"]))
    if any(
        abs(expected - observed) > 1e-6
        for expected, observed in zip(planned_region, map(float, region))
    ):
        raise ValueError("controller power and placement regions differ")
    via_geometries = power_plan["via_geometries"]
    landing_by_layer = {
        "met2": next(item[1] for item in via_geometries["M1M2"] if item[0] == "met2"),
        "met3": next(item[1] for item in via_geometries["M2M3"] if item[0] == "met3"),
    }
    for boundary in range(row_count + 1):
        y = y0 + boundary * row_height
        net = "VGND" if boundary % 2 == 0 else "VDPWR"
        for contact_index, x in enumerate(configured):
            for layer, relative in landing_by_layer.items():
                dx0, dy0, dx1, dy1 = map(float, relative)
                bbox = [
                    max(x0, x + dx0),
                    max(y0, y + dy0),
                    min(x1, x + dx1),
                    min(y1, y + dy1),
                ]
                if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                    raise ValueError("planned controller power contact misses route region")
                result.append({
                    "layer": layer,
                    "bbox_um": bbox,
                    "source_rectangle_count": 1,
                    "kind": "planned_power_contact_obstruction",
                    "net": net,
                    "boundary": boundary,
                    "contact_index": contact_index,
                })
        if boundary % 2 == 0:
            underpass = power_plan["ground_finger_underpass"]
            ux0, ux1 = map(float, underpass["x_span_um"])
            half = float(underpass["width_um"]) / 2.0
            result.append({
                "layer": "met3",
                "bbox_um": [
                    max(x0, ux0), max(y0, y - half),
                    min(x1, ux1), min(y1, y + half),
                ],
                "source_rectangle_count": 1,
                "kind": "planned_power_underpass_obstruction",
                "net": "VGND",
                "boundary": boundary,
            })
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def power_reservation_contract(power_plan: dict[str, Any]) -> dict[str, Any]:
    """Return only the power-plan fields that alter signal-route blockages."""

    region = power_plan["controller_region"]
    underpass = power_plan["ground_finger_underpass"]
    vias = power_plan["via_geometries"]
    return {
        "controller_region": {
            "bbox_um": region["bbox_um"],
            "row_count": region["row_count"],
            "row_height_um": region["row_height_um"],
        },
        "distributed_contact_columns_um": power_plan[
            "distributed_contact_columns_um"
        ],
        "ground_finger_underpass": {
            "layer": underpass["layer"],
            "x_span_um": underpass["x_span_um"],
            "width_um": underpass["width_um"],
        },
        "via_geometries": {
            "M1M2": vias["M1M2"],
            "M2M3": vias["M2M3"],
        },
    }


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def q(value: float) -> int:
    return round(float(value) * DBU)


def tcl_path(path: Path) -> str:
    value = str(path.resolve())
    if "{" in value or "}" in value:
        raise ValueError(f"Tcl path contains a brace: {value}")
    return "{" + value + "}"


def track_values(
    layer: str, axis: int, lower_global: float, local_extent: float
) -> list[float]:
    pitch = TRACK_PITCHES[layer][axis]
    offset = TRACK_OFFSETS[layer][axis]
    first = (offset - lower_global) % pitch
    count = max(1, math.floor((local_extent - first) / pitch) + 1)
    return [round(first + index * pitch, 6) for index in range(count)]


def boundary_pin_plan(
    mapping: dict[str, Any], offset: list[float], size: list[float]
) -> dict[str, dict[str, Any]]:
    input_nets: list[str] = []
    output_nets: list[str] = []
    for port in mapping["ports"].values():
        target = input_nets if port["direction"] == "input" else output_nets
        target.extend(port["nets"])

    # Explicit ordering makes the interface stable across harmless Yosys name
    # changes.  Clock/reset/config enter through the north on preferred M2
    # vertical tracks.  Outputs leave through the west on preferred M3
    # horizontal tracks.
    ordered_inputs = [
        "clk", "rst_n", "ena",
        "beam_select[0]", "beam_select[1]", "beam_select[2]",
        "raw_mode",
        "channel_enable[0]", "channel_enable[1]",
        "channel_enable[2]", "channel_enable[3]",
        "cfg_clk", "cfg_data", "cfg_latch",
    ]
    ordered_outputs = [
        *(f"group_codes[{index}]" for index in range(32)),
        *(f"channel_bias_enable[{index}]" for index in range(4)),
        "mixers_blank",
        *(f"phase_wave[{index}]" for index in range(4)),
    ]
    if set(input_nets) != set(ordered_inputs):
        raise ValueError("mapped V3 input ports differ from the frozen boundary plan")
    if set(output_nets) != set(ordered_outputs):
        raise ValueError("mapped V3 output ports differ from the frozen boundary plan")

    met2_x = track_values("met2", 0, offset[0], size[0])
    met3_y = track_values("met3", 1, offset[1], size[1])
    input_track_indices = [20 + 19 * index for index in range(len(ordered_inputs))]
    if input_track_indices[-1] >= len(met2_x):
        raise ValueError("controller width cannot fit the north boundary inputs")
    # Leave two M3 tracks between output classes so the later top-level fanout
    # can turn without creating tightly coupled parallel buses.
    output_track_indices = [index for index in range(32)]
    output_track_indices += [35 + index for index in range(4)]
    output_track_indices += [41]
    output_track_indices += [45 + index for index in range(4)]
    if output_track_indices[-1] >= len(met3_y):
        raise ValueError("controller height cannot fit the west boundary outputs")

    pins: dict[str, dict[str, Any]] = {}
    for index, net in enumerate(ordered_inputs):
        pins[net] = {
            "direction": "INPUT",
            "layer": "met2",
            "point_um": [met2_x[input_track_indices[index]], size[1]],
            "rect_um": [-0.15, -0.84, 0.15, 0.0],
            "edge": "north",
            "routing_class": (
                "clock" if net in {"clk", "cfg_clk"}
                else "reset" if net == "rst_n" else "control_input"
            ),
        }
    for net, track_index in zip(ordered_outputs, output_track_indices):
        pins[net] = {
            "direction": "OUTPUT",
            "layer": "met3",
            "point_um": [0.0, met3_y[track_index]],
            "rect_um": [0.0, -0.15, 0.84, 0.15],
            "edge": "west",
            "routing_class": (
                "group_code" if net.startswith("group_codes[")
                else "channel_bias" if net.startswith("channel_bias_enable[")
                else "phase" if net.startswith("phase_wave[")
                else "blanking"
            ),
        }
    return pins


def frozen_route_obstructions(
    source_gds: Path, source_top: str, region: list[float]
) -> list[dict[str, Any]]:
    """Return conservative M1-M3 obstacles inherited from the frozen GDS.

    The controller is routed as a local DEF, while the analog and shared
    infrastructure already exists in a separate hierarchical GDS.  Omitting
    those conductors from the router view can produce a DRC-clean controller
    overlay that shorts to the frozen design after assembly.  Flatten only the
    three permitted signal layers, clip them to the controller rectangle, and
    merge connected fragments into conservative component boxes.
    """

    structures, database_um = parse_gds(source_gds)
    rectangles = flatten_orthogonal_rectangles(
        structures, source_top, database_um, set(GDS_ROUTE_LAYERS)
    )
    x0, y0, x1, y1 = map(float, region)
    boundary = (x0, y0, x1, y1)
    result: list[dict[str, Any]] = []
    for gds_layer, def_layer in GDS_ROUTE_LAYERS.items():
        clipped = [
            item
            for rectangle in rectangles[gds_layer]
            if (item := clipped_rectangle(rectangle, boundary)) is not None
        ]
        for component in connected_components(clipped):
            result.append({
                "layer": def_layer,
                "bbox_um": [
                    min(item[0] for item in component),
                    min(item[1] for item in component),
                    max(item[2] for item in component),
                    max(item[3] for item in component),
                ],
                "source_rectangle_count": len(component),
                "kind": "frozen_gds_route_obstruction",
            })
    return sorted(
        result,
        key=lambda item: (item["layer"], *item["bbox_um"]),
    )


def build_def(
    placement: dict[str, Any],
    mapping: dict[str, Any],
    obstructions: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    x0, y0, x1, y1 = map(float, placement["region"]["bbox_um"])
    width, height = x1 - x0, y1 - y0
    offset = [x0, y0]
    all_components = (
        placement["placements"] + placement["well_taps"] + placement["fillers"]
    )
    component_ids = {
        item["instance"]: f"U{index:05d}"
        for index, item in enumerate(
            sorted(all_components, key=lambda value: value["instance"])
        )
    }
    net_ids = {
        net: f"N{index:04d}" for index, net in enumerate(sorted(mapping["nets"]))
    }
    pins = boundary_pin_plan(mapping, offset, [width, height])
    pin_ids = {
        net: f"P{index:03d}" for index, net in enumerate(sorted(pins))
    }

    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        "DESIGN v3_physical_control_internal ;",
        f"UNITS DISTANCE MICRONS {DBU} ;",
        f"DIEAREA ( 0 0 ) ( {q(width)} {q(height)} ) ;",
    ]
    for layer in ROUTING_LAYERS:
        for direction, axis in (("X", 0), ("Y", 1)):
            values = track_values(layer, axis, offset[axis], (width, height)[axis])
            lines.append(
                f"TRACKS {direction} {q(values[0])} DO {len(values)} "
                f"STEP {q(TRACK_PITCHES[layer][axis])} LAYER {layer} ;"
            )

    lines.append(f"COMPONENTS {len(all_components)} ;")
    for item in sorted(all_components, key=lambda value: value["instance"]):
        px, py = map(float, item["origin_um"])
        lines.append(
            f"- {component_ids[item['instance']]} {item['cell']} + FIXED "
            f"( {q(px - x0)} {q(py - y0)} ) {ORIENTATIONS[item['orientation']]} ;"
        )
    lines.append("END COMPONENTS")

    lines.append(f"PINS {len(pins)} ;")
    for net in sorted(pins):
        pin = pins[net]
        px, py = pin["point_um"]
        rx0, ry0, rx1, ry1 = pin["rect_um"]
        use = "CLOCK" if pin["routing_class"] == "clock" else "SIGNAL"
        lines.extend((
            f"- {pin_ids[net]} + NET {net_ids[net]} + DIRECTION {pin['direction']} + USE {use}",
            f"  + PORT + LAYER {pin['layer']} "
            f"( {q(rx0)} {q(ry0)} ) ( {q(rx1)} {q(ry1)} )",
            f"  + FIXED ( {q(px)} {q(py)} ) N ;",
        ))
    lines.append("END PINS")

    lines.append(f"BLOCKAGES {len(obstructions)} ;")
    for item in obstructions:
        bx0, by0, bx1, by1 = map(float, item["bbox_um"])
        if bx0 < x0 - 1e-9 or by0 < y0 - 1e-9 or bx1 > x1 + 1e-9 or by1 > y1 + 1e-9:
            raise ValueError("frozen route obstruction exceeds the controller region")
        lines.extend((
            f"- LAYER {item['layer']}",
            f"  RECT ( {q(bx0 - x0)} {q(by0 - y0)} ) "
            f"( {q(bx1 - x0)} {q(by1 - y0)} ) ;",
        ))
    lines.append("END BLOCKAGES")

    cells_by_name = {item["instance"]: item for item in mapping["cells"]}
    lines.append(f"NETS {len(mapping['nets'])} ;")
    endpoint_counts: dict[str, int] = {}
    for net in sorted(mapping["nets"]):
        endpoints = list(mapping["nets"][net])
        if net in pins:
            endpoints.append({"instance": "PIN", "pin": pin_ids[net]})
        if len(endpoints) < 2:
            raise ValueError(f"{net}: route has fewer than two endpoints")
        endpoint_counts[net] = len(endpoints)
        lines.append(f"- {net_ids[net]}")
        for endpoint in endpoints:
            if endpoint["instance"] == "PIN":
                lines.append(f"  ( PIN {endpoint['pin']} )")
            else:
                instance = endpoint["instance"]
                if instance not in cells_by_name or instance not in component_ids:
                    raise ValueError(f"{net}: absent component {instance}")
                lines.append(f"  ( {component_ids[instance]} {endpoint['pin']} )")
        lines.append(";")
    lines.extend(("END NETS", "END DESIGN", ""))

    report = {
        "schema_version": 1,
        "status": "generated",
        "scope": "shared V3 controller internal signal routing through fixed boundary handoffs; power and top-level handoff fanout excluded",
        "design": "v3_physical_control_internal",
        "coordinate_offset_um": offset,
        "diearea_um": [0.0, 0.0, width, height],
        "component_count": len(all_components),
        "functional_component_count": len(placement["placements"]),
        "well_tap_count": len(placement["well_taps"]),
        "filler_count": len(placement["fillers"]),
        "net_count": len(mapping["nets"]),
        "pin_count": len(pins),
        "endpoint_count": sum(endpoint_counts.values()),
        "frozen_route_obstruction_count": sum(
            item["kind"] == "frozen_gds_route_obstruction" for item in obstructions
        ),
        "planned_power_contact_obstruction_count": sum(
            item["kind"] == "planned_power_contact_obstruction" for item in obstructions
        ),
        "planned_power_underpass_obstruction_count": sum(
            item["kind"] == "planned_power_underpass_obstruction" for item in obstructions
        ),
        "route_obstruction_count": len(obstructions),
        "frozen_route_obstructions": [
            item for item in obstructions
            if item["kind"] == "frozen_gds_route_obstruction"
        ],
        "planned_power_contact_obstructions": [
            item for item in obstructions
            if item["kind"] == "planned_power_contact_obstruction"
        ],
        "planned_power_underpass_obstructions": [
            item for item in obstructions
            if item["kind"] == "planned_power_underpass_obstruction"
        ],
        "component_ids": {value: key for key, value in component_ids.items()},
        "net_ids": {value: key for key, value in net_ids.items()},
        "pin_ids": {value: key for key, value in pin_ids.items()},
        "boundary_pins": pins,
        "policy": {
            "fixed_placement": True,
            "foundry_lef_pin_access_only": True,
            "signal_layers": ["met1", "met2", "met3"],
            "metal4_reserved": True,
            "power_routing_is_separate_gate": True,
            "external_handoff_fanout_is_separate_gate": True,
            "frozen_gds_m1_m2_m3_are_explicit_route_obstructions": True,
            "distributed_power_contacts_are_reserved_before_signal_routing": True,
            "ground_finger_underpasses_are_reserved_before_signal_routing": True,
            "no_manual_internal_preroutes": True,
        },
    }
    return "\n".join(lines), report


def build_route_tcl(
    technology_lef: Path, cell_lef: Path, workdir: Path, threads: int
) -> str:
    return "\n".join((
        "# Fixed-placement production route for the shared V3 controller",
        f"set_thread_count {threads}",
        f"read_lef {tcl_path(technology_lef)}",
        f"read_lef {tcl_path(cell_lef)}",
        f"read_def {tcl_path(workdir / 'input.def')}",
        "set_routing_layers -signal met1-met3 -clock met1-met3",
        "set_global_routing_layer_adjustment met1 0.25",
        "set_global_routing_layer_adjustment met2 0.15",
        "set_global_routing_layer_adjustment met3 0.10",
        f"global_route -guide_file {tcl_path(workdir / 'route.guide')} "
        f"-congestion_iterations 150 -congestion_report_file {tcl_path(workdir / 'congestion.rpt')} -verbose",
        f"detailed_route -output_drc {tcl_path(workdir / 'detailed_route_drc.rpt')} "
        f"-output_guide_coverage {tcl_path(workdir / 'guide_coverage.csv')} "
        "-droute_end_iter 64 -bottom_routing_layer met1 -top_routing_layer met3 "
        "-clean_patches -verbose 1",
        f"report_wire_length -net * -global_route -detailed_route -verbose "
        f"-file {tcl_path(workdir / 'wire_length.csv')}",
        f"write_def {tcl_path(workdir / 'routed.def')}",
        f"write_db {tcl_path(workdir / 'routed.odb')}",
        "exit",
        "",
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--placement", type=Path,
        default=ROOT / "build/v3/control_placement/physical_control_placement.json",
    )
    parser.add_argument(
        "--mapping", type=Path,
        default=ROOT / "build/v3/control_mapping/physical_mapping.json",
    )
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument("--cell-lef", type=Path, required=True)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal",
    )
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument(
        "--source-gds", type=Path,
        default=ROOT / "v3/frozen/four_channel_power_integration/v3_four_channel_power_integration.gds",
    )
    parser.add_argument("--source-top", default="v3_four_channel_power_integration")
    parser.add_argument(
        "--power-plan", type=Path,
        default=ROOT / "v3/layout/physical_control_power_plan.json",
    )
    args = parser.parse_args()
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be in [1, 32]")
    placement = json.loads(args.placement.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    obstructions = frozen_route_obstructions(
        args.source_gds,
        args.source_top,
        list(placement["region"]["bbox_um"]),
    )
    power_plan = json.loads(args.power_plan.read_text(encoding="utf-8"))
    obstructions.extend(
        planned_power_contact_obstructions(
            power_plan, list(placement["region"]["bbox_um"])
        )
    )
    text, report = build_def(placement, mapping, obstructions)
    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        build_route_tcl(args.technology_lef, args.cell_lef, args.workdir, args.threads),
        encoding="utf-8",
    )
    reservation_contract = power_reservation_contract(power_plan)
    report["provenance"] = {
        "placement": str(args.placement),
        "placement_sha256": sha256(args.placement),
        "mapping": str(args.mapping),
        "mapping_sha256": sha256(args.mapping),
        "technology_lef": str(args.technology_lef),
        "technology_lef_sha256": sha256(args.technology_lef),
        "cell_lef": str(args.cell_lef),
        "cell_lef_sha256": sha256(args.cell_lef),
        "frozen_source_gds": str(args.source_gds),
        "frozen_source_gds_sha256": sha256(args.source_gds),
        "frozen_source_top": args.source_top,
        "power_plan": str(args.power_plan),
        "power_reservation_contract": reservation_contract,
        "power_reservation_contract_sha256": canonical_json_sha256(
            reservation_contract
        ),
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__)),
    }
    (args.workdir / "input_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "components": report["component_count"],
        "nets": report["net_count"],
        "pins": report["pin_count"],
        "frozen_route_obstructions": report["frozen_route_obstruction_count"],
        "planned_power_contact_obstructions": report[
            "planned_power_contact_obstruction_count"
        ],
        "planned_power_underpass_obstructions": report[
            "planned_power_underpass_obstruction_count"
        ],
        "metal4_reserved": report["policy"]["metal4_reserved"],
    }, indent=2))


if __name__ == "__main__":
    main()
