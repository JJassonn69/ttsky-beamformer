#!/usr/bin/env python3
"""Generate bounded qrouter/OpenROAD jobs for the V2 control nets.

OpenROAD owns the complete standard-cell portion of every routed net, including
trim and quadrature handoffs.  The analog overlays begin at fixed upper-metal
boundary pins, so a later hand-authored via stack can never short a router wire
that legally passes above an otherwise LI-only cell pin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


DBU = 1000
QROUTER_ROUTED_CLASSES = {"local_direct", "regional_trunk"}
OPENROAD_ROUTED_CLASSES = {
    "local_direct",
    "regional_trunk",
    "trim_handoff",
    "quadrature_handoff",
    "direct_boundary",
    "service_tree",
    "phase_handoff",
    "external_input",
}
TRIM_HANDOFF_LAYER = "met3"
TRIM_HANDOFF_X_UM = 184.62
# The handoffs are on 0.64 um centers.  A 0.30 um-tall by 0.84 um-wide M3 pin
# preserves 0.34 um vertical spacing and has 0.252 um^2 area, safely above the
# 0.240 um^2 foundry minimum.  The direct GDS writer emits this DEF pin shape
# as part of the routed net; it is not merely an abstract routing target.
TRIM_HANDOFF_PIN_RECT_UM = [-0.42, -0.15, 0.42, 0.15]
QUADRATURE_HANDOFF_LAYER = "met3"
# This is an exact global M3 routing track immediately below the fixed global
# control rows.  Four widely spaced pins preserve access while keeping the
# later analog-only M2 drops short and monotonic.
QUADRATURE_HANDOFF_Y_UM = 194.82
QUADRATURE_HANDOFF_PIN_RECT_UM = [-0.42, -0.15, 0.42, 0.15]
SERVICE_TOP_PIN_RECT_UM = [-0.35, -0.20, 0.35, 0.20]
EXTERNAL_TOP_PIN_RECT_UM = [-0.35, -0.20, 0.35, 0.20]
EXTERNAL_TOP_PIN_NAMES = {
    "cfg_data": "I_CFG_DATA",
    "channel_enable[0]": "I_CH_EN0",
    "channel_enable[1]": "I_CH_EN1",
    "channel_enable[2]": "I_CH_EN2",
    "channel_enable[3]": "I_CH_EN3",
    "manual_mode": "I_MANUAL",
    "beam_select[0]": "I_BEAM0",
    "beam_select[1]": "I_BEAM1",
    "ena": "I_ENA",
}
PHASE_HANDOFF_LAYER = "met2"
PHASE_HANDOFF_PIN_RECT_UM = [-0.42, -0.15, 0.42, 0.15]
LOCAL_PAIR_MAX_HPWL_UM = 3.0
ROUTING_LAYERS = ("li1", "met1", "met2", "met3", "met4")
GEOMETRY_TO_LEF_LAYER = {
    "locali": "li1",
    "metal1": "met1",
    "metal2": "met2",
    "metal3": "met3",
    "metal4": "met4",
}
LAYER_WIDTHS = {
    "li1": 0.17,
    "met1": 0.14,
    "met2": 0.14,
    "met3": 0.30,
    "met4": 0.30,
}
LAYER_PITCHES = {
    "li1": 0.46,
    "met1": 0.34,
    "met2": 0.46,
    "met3": 0.68,
    "met4": 0.92,
}
LAYER_DIRECTIONS = {
    "li1": "vertical",
    "met1": "horizontal",
    "met2": "vertical",
    "met3": "horizontal",
    "met4": "vertical",
}
LAYER_OFFSETS = {
    "li1": 0.23,
    "met1": 0.17,
    "met2": 0.23,
    "met3": 0.34,
    "met4": 0.46,
}
# The SKY130 HD technology LEF gives li1 an asymmetric 0.46 x 0.34 um
# routing lattice.  OpenROAD expects a complete X/Y track structure even
# though FastRoute uses only the preferred-direction tracks.  qrouter uses the
# compact preferred-axis form below, so keep the full lattice separate.
OPENROAD_TRACK_PITCHES = {
    "li1": (0.46, 0.34),
    "met1": (0.34, 0.34),
    "met2": (0.46, 0.46),
    "met3": (0.68, 0.68),
    "met4": (0.92, 0.92),
}
OPENROAD_TRACK_OFFSETS = {
    "li1": (0.23, 0.17),
    "met1": (0.17, 0.17),
    "met2": (0.23, 0.23),
    "met3": (0.34, 0.34),
    "met4": (0.46, 0.46),
}
ORIENTATIONS = {"R0": "N", "MX": "FS", "MY": "FN", "R180": "S"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dbu(value: float) -> int:
    return round(float(value) * DBU)


def manufacturing_grid(value: float) -> float:
    """Snap a global coordinate to the SKY130 5 nm manufacturing grid."""

    return round(round(float(value) / 0.005) * 0.005, 6)


def intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def clipped(a: list[float], b: list[float]) -> list[float] | None:
    result = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return result if result[0] < result[2] and result[1] < result[3] else None


def routed_net_copy(item: dict[str, Any], backend: str) -> dict[str, Any]:
    """Return the endpoints owned by this routing backend.

    Analog endpoints are represented by fixed M3 boundary pins.  This makes
    TritonRoute own every standard-cell access and gives each later analog
    overlay one unambiguous, router-protected connection point.
    """

    result = dict(item)
    endpoints = [dict(endpoint) for endpoint in item["endpoints"]]
    if backend == "openroad" and item["class"] == "phase_handoff":
        standard = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "standard_cell_pin"
        ]
        handoffs = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "phase_selector_handoff"
        ]
        if len(standard) != 1 or len(handoffs) != 1:
            raise ValueError(
                f"{item['net']}: expected one standard-cell pin and one phase handoff"
            )
        handoff = handoffs[0]
        signal = item["net"].split("[", 1)[0]
        channel = int(item["net"].split("[")[-1].rstrip("]"))
        signal_index = {"phase_select0": 0, "phase_select1": 1,
                        "phase_enable": 2}[signal]
        top_pin = {
            "kind": "top_level_pin",
            "pin": f"P{signal_index}{channel}",
            "direction": "OUTPUT",
            "layer": PHASE_HANDOFF_LAYER,
            "point_um": list(map(manufacturing_grid, handoff["point_um"])),
            "rect_um": list(PHASE_HANDOFF_PIN_RECT_UM),
            "region": standard[0]["region"],
        }
        endpoints = standard + [top_pin]
    elif backend == "openroad" and item["class"] == "trim_handoff":
        standard = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "standard_cell_pin"
        ]
        handoffs = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "trim_bus_handoff"
        ]
        if len(standard) != 2 or len(handoffs) != 1:
            raise ValueError(
                f"{item['net']}: expected two standard-cell pins and one trim handoff"
            )
        handoff = handoffs[0]
        bit = int(item["net"].split("[")[-1].rstrip("]"))
        top_pin = {
            "kind": "top_level_pin",
            "pin": f"T{bit:02d}",
            "direction": "OUTPUT",
            "layer": TRIM_HANDOFF_LAYER,
            "point_um": [TRIM_HANDOFF_X_UM, float(handoff["point_um"][1])],
            "rect_um": list(TRIM_HANDOFF_PIN_RECT_UM),
            "region": standard[0]["region"],
            "source_handoff_point_um": list(map(float, handoff["point_um"])),
            "analog_sink_point_um": list(map(float, handoff["sink_point_um"])),
        }
        endpoints = standard + [top_pin]
    elif backend == "openroad" and item["class"] == "quadrature_handoff":
        standard = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "standard_cell_pin"
        ]
        handoffs = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "quadrature_root_handoff"
        ]
        if not standard or len(handoffs) != 1:
            raise ValueError(
                f"{item['net']}: expected standard-cell pins and one quadrature handoff"
            )
        handoff = handoffs[0]
        index = int(item["net"].split("[")[-1].rstrip("]"))
        top_pin = {
            "kind": "top_level_pin",
            "pin": f"Q{index}",
            "direction": "OUTPUT",
            "layer": QUADRATURE_HANDOFF_LAYER,
            "point_um": [
                manufacturing_grid(handoff["point_um"][0]),
                manufacturing_grid(QUADRATURE_HANDOFF_Y_UM),
            ],
            "rect_um": list(QUADRATURE_HANDOFF_PIN_RECT_UM),
            "region": standard[0]["region"],
            "source_handoff_point_um": list(map(float, handoff["point_um"])),
        }
        endpoints = standard + [top_pin]
    elif backend == "openroad" and item["class"] == "service_tree":
        standard = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "standard_cell_pin"
        ]
        external = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "external_top_pin"
        ]
        if len(external) > 1:
            raise ValueError(f"{item['net']}: expected at most one external service pin")
        top_pins = []
        for endpoint in external:
            top_pins.append({
                "kind": "top_level_pin",
                "pin": f"S_{item['net'].upper()}",
                "direction": "INPUT",
                "layer": GEOMETRY_TO_LEF_LAYER[endpoint["layer"]],
                "point_um": list(map(float, endpoint["point_um"])),
                "rect_um": list(SERVICE_TOP_PIN_RECT_UM),
                "region": "global_control_core",
            })
        endpoints = standard + top_pins
    elif backend == "openroad" and item["class"] == "external_input":
        standard = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "standard_cell_pin"
        ]
        external = [
            endpoint for endpoint in endpoints
            if endpoint["kind"] == "external_top_pin"
        ]
        if len(standard) != 1 or len(external) != 1:
            raise ValueError(
                f"{item['net']}: expected one standard-cell input and one external pin"
            )
        if item["net"] not in EXTERNAL_TOP_PIN_NAMES:
            raise ValueError(f"{item['net']}: missing stable external top-pin name")
        top_pin = {
            "kind": "top_level_pin",
            "pin": EXTERNAL_TOP_PIN_NAMES[item["net"]],
            "direction": "INPUT",
            "layer": GEOMETRY_TO_LEF_LAYER[external[0]["layer"]],
            "point_um": list(map(float, external[0]["point_um"])),
            "rect_um": list(EXTERNAL_TOP_PIN_RECT_UM),
            "region": standard[0]["region"],
        }
        endpoints = standard + [top_pin]
    result["endpoints"] = endpoints
    xs = [float(endpoint["point_um"][0]) for endpoint in endpoints]
    ys = [float(endpoint["point_um"][1]) for endpoint in endpoints]
    result["source_hpwl_um"] = float(item["hpwl_um"])
    result["hpwl_um"] = (max(xs) - min(xs)) + (max(ys) - min(ys))
    return result


def make_config(
    region: str,
    bounds: list[float],
    technology_lef: Path,
    cell_lef: Path,
    priority_nets: list[str],
) -> str:
    lines = [
        f"# Generated production-routing job for {region}",
        "Num_layers 5",
    ]
    for index, layer in enumerate(ROUTING_LAYERS, start=1):
        lines.extend((
            f"Layer_{index}_name {layer}",
            f"Layer_{index}_width {LAYER_WIDTHS[layer]:.2f}",
            f"layer {index} wire pitch {LAYER_PITCHES[layer]:.2f}",
            f"layer {index} {LAYER_DIRECTIONS[layer]}",
        ))
    lines.extend((
        "Num Passes 20",
        "Route Segment Cost 2",
        "Route Via Cost 12",
        "Route Jog Cost 25",
        "Route Crossover Cost 8",
        "Route Block Cost 80",
    ))
    lines.extend(f"Route Priority {net}" for net in priority_nets)
    lines.extend((
        f"X lower bound {bounds[0]:.3f}",
        f"X upper bound {bounds[2]:.3f}",
        f"Y lower bound {bounds[1]:.3f}",
        f"Y upper bound {bounds[3]:.3f}",
        f"lef {technology_lef.resolve()}",
        f"lef {cell_lef.resolve()}",
        "",
    ))
    return "\n".join(lines)


def make_def(
    design: str,
    bounds: list[float],
    components: list[dict[str, Any]],
    component_ids: dict[str, str],
    nets: list[dict[str, Any]],
    net_ids: dict[str, str],
    top_pins: list[dict[str, Any]],
    blockages: list[dict[str, Any]],
    global_offset: list[float],
    *,
    standard_blockages: bool = False,
) -> str:
    lines = [
        "VERSION 5.8 ;",
        'DIVIDERCHAR "/" ;',
        'BUSBITCHARS "[]" ;',
        f"DESIGN {design} ;",
        f"UNITS DISTANCE MICRONS {DBU} ;",
        f"DIEAREA ( {dbu(bounds[0])} {dbu(bounds[1])} ) ( {dbu(bounds[2])} {dbu(bounds[3])} ) ;",
    ]
    # qrouter builds its routing grid when it reaches NETS.  Explicit TRACKS
    # are required; without them its legacy parser has not yet restored the
    # DIEAREA bounds and silently constructs a 1x1 grid.
    for layer in ROUTING_LAYERS:
        if standard_blockages:
            axes = (("X", 0), ("Y", 1))
        else:
            direction = "X" if LAYER_DIRECTIONS[layer] == "vertical" else "Y"
            axes = ((direction, 0 if direction == "X" else 1),)
        for direction, axis in axes:
            if standard_blockages:
                pitch = OPENROAD_TRACK_PITCHES[layer][axis]
                offset = OPENROAD_TRACK_OFFSETS[layer][axis]
            else:
                pitch = LAYER_PITCHES[layer]
                offset = LAYER_OFFSETS[layer]
            first = (offset - global_offset[axis]) % pitch
            extent = bounds[2] if axis == 0 else bounds[3]
            count = max(1, math.floor((extent - first) / pitch) + 1)
            lines.append(
                f"TRACKS {direction} {dbu(first)} DO {count} STEP {dbu(pitch)} "
                f"LAYER {layer} ;"
            )
    lines.append(f"COMPONENTS {len(components)} ;")
    for item in components:
        instance = item["instance"]
        x, y = item["bbox_um"][:2]
        lines.append(
            f" - {component_ids[instance]} {item['cell']} + FIXED "
            f"( {dbu(x)} {dbu(y)} ) {ORIENTATIONS[item['orientation']]} ;"
        )
    lines.append("END COMPONENTS")
    lines.append(f"PINS {len(top_pins)} ;")
    for pin in top_pins:
        x, y = pin["point_um"]
        x0, y0, x1, y1 = pin["rect_um"]
        lines.extend((
            f" - {pin['pin']} + NET {net_ids[pin['net']]} "
            f"+ DIRECTION {pin['direction']} + USE SIGNAL",
            f"   + LAYER {pin['layer']} "
            f"( {dbu(x0)} {dbu(y0)} ) ( {dbu(x1)} {dbu(y1)} )",
            f"   + FIXED ( {dbu(x)} {dbu(y)} ) N ;",
        ))
    lines.append("END PINS")

    lines.append(f"BLOCKAGES {len(blockages)} ;")
    for item in blockages:
        x0, y0, x1, y1 = item["bbox_um"]
        if standard_blockages:
            lines.append(
                f" - LAYER {item['layer']} RECT "
                f"( {dbu(x0)} {dbu(y0)} ) ( {dbu(x1)} {dbu(y1)} ) ;"
            )
        else:
            # qrouter 1.4 reuses its LEF geometry parser for DEF blockages.
            # Each item is therefore a small geometry section whose END must
            # be on its own line; a generic one-line DEF blockage causes it
            # to consume the following blockages and eventually the NETS
            # section.
            lines.extend((
                f" - {item['layer']}",
                f"   RECT ( {dbu(x0)} {dbu(y0)} ) ( {dbu(x1)} {dbu(y1)} ) ;",
                " END",
            ))
    lines.append("END BLOCKAGES")

    lines.append(f"NETS {len(nets)} ;")
    for item in nets:
        # qrouter's classic batch writer expects the net name before it sees
        # the terminating semicolon.  A legal single-line DEF net routes in
        # memory but triggers an uninitialized-name bug during output.
        lines.append(f" - {net_ids[item['net']]}")
        for endpoint in item["endpoints"]:
            if endpoint["kind"] == "standard_cell_pin":
                lines.append(
                    f"   ( {component_ids[endpoint['instance']]} {endpoint['pin']} )"
                )
            elif endpoint["kind"] == "top_level_pin":
                lines.append(f"   ( PIN {endpoint['pin']} )")
            else:
                raise ValueError(
                    f"{item['net']}: unsupported router endpoint {endpoint['kind']}"
                )
        lines.append(" ;")
    lines.extend(("END NETS", "END DESIGN", ""))
    return "\n".join(lines)


def generate(
    placement: dict[str, Any],
    allocation: dict[str, Any],
    power_geometry: dict[str, Any],
    power_plan: dict[str, Any],
    integration: dict[str, Any],
    technology_lef: Path,
    cell_lef: Path,
    output_dir: Path,
    *,
    backend: str = "qrouter",
) -> dict[str, Any]:
    if backend not in {"qrouter", "openroad"}:
        raise ValueError(f"unsupported routing backend {backend}")
    if allocation.get("status") != "pass" or allocation.get("errors"):
        raise ValueError("refusing to route a failed signal allocation")
    if sha256(technology_lef) == sha256(cell_lef):
        raise ValueError("technology and cell LEFs unexpectedly have identical content")

    placement_region_defs = {
        item["name"]: list(map(float, item["bbox"]))
        for item in integration["placement_regions"]
        if item["name"] in placement["regions"]
    }
    if backend == "openroad":
        digital_regions = {
            "global_control_core",
            "phase_configuration_bank",
            "trim_configuration_bank",
        }
        digital_boxes = [placement_region_defs[name] for name in sorted(digital_regions)]
        region_groups = {
            "digital_control": {
                "source_regions": digital_regions,
                "bounds": [
                    min(box[0] for box in digital_boxes),
                    min(box[1] for box in digital_boxes),
                    max(box[2] for box in digital_boxes),
                    max(box[3] for box in digital_boxes),
                ],
            },
        }
    else:
        region_groups = {
            name: {"source_regions": {name}, "bounds": bounds}
            for name, bounds in placement_region_defs.items()
        }
    all_components = placement["placements"] + placement["well_taps"] + placement.get("fillers", [])
    all_component_ids = {
        item["instance"]: f"U{index:05d}"
        for index, item in enumerate(sorted(all_components, key=lambda value: value["instance"]))
    }
    routed_classes = (
        OPENROAD_ROUTED_CLASSES if backend == "openroad" else QROUTER_ROUTED_CLASSES
    )
    internal_nets = [
        routed_net_copy(item, backend)
        for item in allocation["nets"] if item["class"] in routed_classes
    ]
    if len(internal_nets) != sum(allocation["class_counts"][name] for name in routed_classes):
        raise ValueError("internal-net class count disagrees with allocation summary")

    candidate_local_pair_nets = [
        item for item in internal_nets
        if item["net"].endswith("/enabled_d")
        and len(item["endpoints"]) == 2
        and float(item["hpwl_um"]) <= LOCAL_PAIR_MAX_HPWL_UM
    ]
    # qrouter 1.4 cannot reliably escape some compact LI-only mux/FF ports.
    # TritonRoute has a dedicated pin-access stage, so OpenROAD must own every
    # internal net; silently pre-routing the difficult pairs would hide a
    # production-routing gap.
    local_pair_nets = candidate_local_pair_nets if backend == "qrouter" else []
    router_nets = [item for item in internal_nets if item not in local_pair_nets]
    power_shapes = []
    for source in power_geometry["shapes"]:
        layer = GEOMETRY_TO_LEF_LAYER.get(source["layer"])
        if layer is not None:
            power_shapes.append({**source, "layer": layer})
    keepouts = power_plan.get("reserved_keepouts", [])
    jobs: list[dict[str, Any]] = []
    assigned_nets: set[str] = set()
    output_dir.mkdir(parents=True, exist_ok=True)

    for region, group in sorted(region_groups.items()):
        source_regions = set(group["source_regions"])
        bounds = list(group["bounds"])
        if backend == "openroad" and region == "digital_control":
            boundary_pin_boxes = [
                [
                    float(endpoint["point_um"][0]) + float(endpoint["rect_um"][0]),
                    float(endpoint["point_um"][1]) + float(endpoint["rect_um"][1]),
                    float(endpoint["point_um"][0]) + float(endpoint["rect_um"][2]),
                    float(endpoint["point_um"][1]) + float(endpoint["rect_um"][3]),
                ]
                for item in internal_nets
                for endpoint in item["endpoints"]
                if endpoint["kind"] == "top_level_pin"
                and endpoint["region"] in source_regions
            ]
            if boundary_pin_boxes:
                bounds = [
                    min(bounds[0], min(box[0] for box in boundary_pin_boxes) - 0.30),
                    min(bounds[1], min(box[1] for box in boundary_pin_boxes) - 0.30),
                    max(bounds[2], max(box[2] for box in boundary_pin_boxes) + 0.30),
                    max(bounds[3], max(box[3] for box in boundary_pin_boxes) + 0.30),
                ]
        offset_x, offset_y = bounds[:2]
        local_bounds = [0.0, 0.0, bounds[2] - offset_x, bounds[3] - offset_y]
        source_components = [item for item in all_components if item["region"] in source_regions]
        components = []
        for item in source_components:
            local = dict(item)
            local["bbox_um"] = [
                item["bbox_um"][0] - offset_x,
                item["bbox_um"][1] - offset_y,
                item["bbox_um"][2] - offset_x,
                item["bbox_um"][3] - offset_y,
            ]
            components.append(local)
        available = {item["instance"] for item in components}
        nets: list[dict[str, Any]] = []
        for item in router_nets:
            endpoint_regions = {endpoint["region"] for endpoint in item["endpoints"]}
            if endpoint_regions and endpoint_regions <= source_regions:
                missing = {
                    endpoint["instance"] for endpoint in item["endpoints"]
                    if endpoint["kind"] == "standard_cell_pin"
                } - available
                if missing:
                    raise ValueError(f"{item['net']}: endpoints absent from {region}: {sorted(missing)}")
                nets.append(item)
                assigned_nets.add(item["net"])
            elif endpoint_regions & source_regions:
                raise ValueError(
                    f"internal net {item['net']} crosses placement regions {sorted(endpoint_regions)}"
                )

        net_ids = {
            item["net"]: f"N{index:04d}"
            for index, item in enumerate(sorted(nets, key=lambda value: value["net"]))
        }
        top_pins = []
        for item in nets:
            for endpoint in item["endpoints"]:
                if endpoint["kind"] != "top_level_pin":
                    continue
                local = dict(endpoint)
                local["net"] = item["net"]
                local["point_um"] = [
                    float(endpoint["point_um"][0]) - offset_x,
                    float(endpoint["point_um"][1]) - offset_y,
                ]
                top_pins.append(local)
        blockages: list[dict[str, Any]] = []
        seen_blockages: set[tuple[Any, ...]] = set()
        for item in power_shapes:
            box = clipped(list(map(float, item["bbox_um"])), bounds)
            if box is None:
                continue
            box = [box[0] - offset_x, box[1] - offset_y, box[2] - offset_x, box[3] - offset_y]
            key = (item["layer"], *(round(value, 6) for value in box))
            if key not in seen_blockages:
                seen_blockages.add(key)
                blockages.append({"layer": item["layer"], "bbox_um": box, "owner": item["owner"]})
        for item in keepouts:
            source_box = item.get("bbox")
            if source_box is None:
                source_box = [*item["x_span"], *item["y_span"]]
                source_box = [source_box[0], source_box[2], source_box[1], source_box[3]]
            box = clipped(list(map(float, source_box)), bounds)
            if box is None:
                continue
            box = [box[0] - offset_x, box[1] - offset_y, box[2] - offset_x, box[3] - offset_y]
            layers = item.get("layers", [item["layer"]] if "layer" in item else ROUTING_LAYERS)
            for layer in layers:
                layer = GEOMETRY_TO_LEF_LAYER.get(layer, layer)
                if layer not in ROUTING_LAYERS:
                    continue
                key = (layer, *(round(value, 6) for value in box))
                if key not in seen_blockages:
                    seen_blockages.add(key)
                    blockages.append({"layer": layer, "bbox_um": box, "owner": item["name"]})

        stem = region.replace("_", "-")
        def_path = output_dir / f"{stem}.def"
        cfg_path = output_dir / f"{stem}.cfg"
        design = f"v2_{region}_internal"
        def_path.write_text(make_def(
            design, local_bounds, components, all_component_ids, nets, net_ids, top_pins, blockages,
            [offset_x, offset_y], standard_blockages=backend == "openroad",
        ), encoding="utf-8")
        # Route the compact mux-to-FF D connections before broad fanout nets.
        # They live inside the densest cell rows and lose all legal via sites
        # if a less critical trunk is allowed to occupy the escape tracks.
        local_pair_priority = [
            net_ids[item["net"]] for item in nets if item["net"].endswith("/enabled_d")
        ]
        clock_priority = [
            net_ids[item["net"]] for item in nets
            if "clk" in item["net"].lower() or "clock" in item["net"].lower()
        ]
        priority = local_pair_priority + [item for item in clock_priority if item not in local_pair_priority]
        job = {
            "region": region,
            "design": design,
            "bounds_um": bounds,
            "router_bounds_um": local_bounds,
            "coordinate_offset_um": [offset_x, offset_y],
            "component_count": len(components),
            "signal_component_count": sum(item["role"] not in ("well_tap", "power_filler") for item in components),
            "well_tap_count": sum(item["role"] == "well_tap" for item in components),
            "filler_count": sum(item["role"] == "power_filler" for item in components),
            "net_count": len(nets),
            "endpoint_count": sum(len(item["endpoints"]) for item in nets),
            "top_pin_count": len(top_pins),
            "top_pins": {
                item["pin"]: {
                    "net": item["net"],
                    "layer": item["layer"],
                    "point_um": item["point_um"],
                    "rect_um": item["rect_um"],
                }
                for item in top_pins
            },
            "blockage_count": len(blockages),
            "def": str(def_path),
            "component_ids": {
                all_component_ids[item["instance"]]: item["instance"] for item in components
            },
            "net_ids": {value: key for key, value in net_ids.items()},
        }
        if backend == "qrouter":
            cfg_path.write_text(make_config(
                region, local_bounds, technology_lef, cell_lef, priority
            ), encoding="utf-8")
            job["config"] = str(cfg_path)
        jobs.append(job)

    missing_nets = {item["net"] for item in router_nets} - assigned_nets
    if missing_nets:
        raise ValueError(f"internal nets were not assigned to a bounded job: {sorted(missing_nets)}")
    report = {
        "schema_version": 1,
        "status": "pass",
        "policy": {
            "route_classes": sorted(routed_classes),
            "trim_handoff_boundary_pins_are_router_owned": backend == "openroad",
            "quadrature_handoff_boundary_pins_are_router_owned": backend == "openroad",
            "phase_handoff_boundary_pins_are_router_owned": backend == "openroad",
            "service_trees_and_external_pins_are_router_owned": backend == "openroad",
            "all_external_digital_inputs_are_router_owned": backend == "openroad",
            "global_and_phase_regions_are_jointly_routed": backend == "openroad",
            "one_job_per_placement_region": backend == "qrouter",
            "metal5_allowed": False,
            "existing_power_is_a_routing_blockage": True,
            "all_cell_pin_access_comes_from_foundry_lef": True,
            "short_mux_ff_pairs_are_prerouted": backend == "qrouter",
            "all_internal_nets_are_router_owned": backend == "openroad",
        },
        "source_sha256": {
            "technology_lef": sha256(technology_lef),
            "cell_lef": sha256(cell_lef),
        },
        "total_internal_nets": len(internal_nets),
        "backend": backend,
        "router_net_count": len(router_nets),
        "qrouter_net_count": len(router_nets) if backend == "qrouter" else 0,
        "openroad_net_count": len(router_nets) if backend == "openroad" else 0,
        "local_pair_preroute_count": len(local_pair_nets),
        "local_pair_preroutes": [
            {
                "net": item["net"],
                "region": item["endpoints"][0]["region"],
                "hpwl_um": item["hpwl_um"],
            }
            for item in sorted(local_pair_nets, key=lambda value: value["net"])
        ],
        "jobs": jobs,
    }
    (output_dir / f"{backend}_jobs.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement", type=Path, default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--power-geometry", type=Path, default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--power-plan", type=Path, default=Path("v2/layout/control_power_plan.json"))
    parser.add_argument("--integration", type=Path, default=Path("v2/layout/integration_plan.json"))
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument("--cell-lef", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("build/v2/control_routing/qrouter"))
    parser.add_argument("--backend", choices=("qrouter", "openroad"), default="qrouter")
    args = parser.parse_args()
    result = generate(
        json.loads(args.placement.read_text(encoding="utf-8")),
        json.loads(args.allocation.read_text(encoding="utf-8")),
        json.loads(args.power_geometry.read_text(encoding="utf-8")),
        json.loads(args.power_plan.read_text(encoding="utf-8")),
        json.loads(args.integration.read_text(encoding="utf-8")),
        args.technology_lef,
        args.cell_lef,
        args.output_dir,
        backend=args.backend,
    )
    print(json.dumps({
        "status": result["status"],
        "jobs": [{"region": item["region"], "nets": item["net_count"]} for item in result["jobs"]],
        "total_internal_nets": result["total_internal_nets"],
        "backend": result["backend"],
        "router_nets": result["router_net_count"],
        "qrouter_nets": result["qrouter_net_count"],
        "openroad_nets": result["openroad_net_count"],
        "local_pair_preroutes": result["local_pair_preroute_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
