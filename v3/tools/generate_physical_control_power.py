#!/usr/bin/env python3
"""Generate and attach the V3 centralized-controller power network.

The topology deliberately keeps all M1-to-M4 stacks outside the signal-routed
controller rectangle.  This preserves the closed 305-net signal checkpoint
while still giving every alternating standard-cell row rail two independent
upper-metal contacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET1,
    MET2,
    MET3,
    MET4,
    VIA1,
    VIA2,
    VIA3,
    flatten_orthogonal_rectangles,
    parse_gds,
)
from assemble_route_overlay_gds import assemble as attach_overlay  # noqa: E402
from generate_control_openroad_overlay import direct_gds, rectangle  # noqa: E402


LAYER_TO_GDS = {
    "met1": MET1,
    "via": VIA1,
    "met2": MET2,
    "via2": VIA2,
    "met3": MET3,
    "via3": VIA3,
    "met4": MET4,
}
CONDUCTOR_LAYERS = ("met1", "met2", "met3", "met4")
VIA_ADJACENCY = {
    "via": ("met1", "met2"),
    "via2": ("met2", "met3"),
    "via3": ("met3", "met4"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boxes_touch(first: list[float], second: list[float]) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def boxes_overlap(first: list[float], second: tuple[float, float, float, float]) -> bool:
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def spacing(first: list[float], second: list[float]) -> float:
    dx = max(second[0] - first[2], first[0] - second[2], 0.0)
    dy = max(second[1] - first[3], first[1] - second[3], 0.0)
    if dx == 0.0:
        return dy
    if dy == 0.0:
        return dx
    return (dx * dx + dy * dy) ** 0.5


class Geometry:
    def __init__(self, via_geometries: dict[str, Any]) -> None:
        self.shapes: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []
        self.via_geometries = via_geometries

    def rect(
        self,
        net: str,
        layer: str,
        bbox: list[float],
        kind: str,
        owner: str,
    ) -> None:
        self.shapes.append({
            "net": net,
            "layer": layer,
            "bbox_um": rectangle(*map(float, bbox)),
            "kind": kind,
            "owner": owner,
        })

    def wire(
        self,
        net: str,
        layer: str,
        start: list[float],
        end: list[float],
        width: float,
        kind: str,
        owner: str,
    ) -> None:
        x0, y0 = map(float, start)
        x1, y1 = map(float, end)
        half = float(width) / 2.0
        if abs(x0 - x1) < 1e-12:
            self.rect(net, layer, [x0 - half, y0, x0 + half, y1], kind, owner)
        elif abs(y0 - y1) < 1e-12:
            self.rect(net, layer, [x0, y0 - half, x1, y0 + half], kind, owner)
        else:
            raise ValueError(f"{owner}: non-Manhattan power route")

    def via(self, net: str, family: str, x: float, y: float, owner: str) -> None:
        for layer, relative in self.via_geometries[family]:
            dx0, dy0, dx1, dy1 = map(float, relative)
            self.rect(
                net,
                layer,
                [x + dx0, y + dy0, x + dx1, y + dy1],
                f"{family}_shape",
                owner,
            )

    def m1_to_m4(self, net: str, x: float, y: float, owner: str) -> None:
        self.via(net, "M1M2", x, y, owner)
        self.via(net, "M2M3", x, y, owner)
        self.via(net, "M3M4", x, y, owner)


def deduplicate(shapes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in shapes:
        key = (item["net"], item["layer"], *item["bbox_um"])
        unique.setdefault(key, item)
    return list(unique.values())


def connectivity_audit(shapes: list[dict[str, Any]], net: str) -> dict[str, Any]:
    selected = [item for item in shapes if item["net"] == net]
    graph: dict[int, set[int]] = defaultdict(set)
    by_layer: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(selected):
        by_layer[item["layer"]].append(index)
    for indices in by_layer.values():
        for offset, first_index in enumerate(indices):
            for second_index in indices[offset + 1 :]:
                if boxes_touch(
                    selected[first_index]["bbox_um"], selected[second_index]["bbox_um"]
                ):
                    graph[first_index].add(second_index)
                    graph[second_index].add(first_index)

    orphan_vias: list[dict[str, Any]] = []
    for via_layer, adjacent in VIA_ADJACENCY.items():
        for via_index in by_layer[via_layer]:
            missing: list[str] = []
            for conductor_layer in adjacent:
                hits = [
                    index
                    for index in by_layer[conductor_layer]
                    if boxes_touch(
                        selected[via_index]["bbox_um"], selected[index]["bbox_um"]
                    )
                ]
                if not hits:
                    missing.append(conductor_layer)
                for index in hits:
                    graph[via_index].add(index)
                    graph[index].add(via_index)
            if missing:
                orphan_vias.append({
                    "owner": selected[via_index]["owner"],
                    "layer": via_layer,
                    "missing": missing,
                })

    unseen = set(range(len(selected)))
    component_sizes: list[int] = []
    while unseen:
        start = unseen.pop()
        queue = deque([start])
        count = 0
        while queue:
            current = queue.popleft()
            count += 1
            for neighbor in graph[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        component_sizes.append(count)
    return {
        "shape_count": len(selected),
        "connected_component_count": len(component_sizes),
        "component_sizes": sorted(component_sizes, reverse=True),
        "orphan_vias": orphan_vias,
    }


def generate(plan: dict[str, Any], source: Path) -> dict[str, Any]:
    checkpoint = plan["source_checkpoint"]
    if sha256(source) != checkpoint["sha256"]:
        raise ValueError("controller signal-route GDS differs from the frozen power source")
    gate = ROOT / checkpoint["physical_gate"]
    if sha256(gate) != checkpoint["physical_gate_sha256"]:
        raise ValueError("controller signal-route evidence differs from the frozen power source")
    if json.loads(gate.read_text(encoding="utf-8"))["status"] != "pass":
        raise ValueError("controller signal-route gate is not closed")

    rules = plan["rules"]
    region = plan["controller_region"]
    x0, y0, x1, y1 = map(float, region["bbox_um"])
    row_count = int(region["row_count"])
    row_height = float(region["row_height_um"])
    extension = float(region["rail_extension_x_um"])
    geometry = Geometry(plan["via_geometries"])
    rail_records: list[dict[str, Any]] = []
    contact_records: list[dict[str, Any]] = []

    for boundary in range(row_count + 1):
        net = "VGND" if boundary % 2 == 0 else "VDPWR"
        y = y0 + boundary * row_height
        geometry.wire(
            net,
            "met1",
            [x0, y],
            [extension, y],
            float(rules["m1_rail_width_um"]),
            "standard_cell_row_rail",
            f"row_{boundary:02d}_{net}",
        )
        spine_x = float(plan["m4_spines"][net]["x_um"])
        contacts = list(map(float, plan["distributed_contact_columns_um"]))
        for index, contact_x in enumerate(contacts):
            owner = f"row_{boundary:02d}_{net}_contact_{index}"
            geometry.m1_to_m4(net, contact_x, y, owner)
            contact_records.append({
                "boundary": boundary,
                "net": net,
                "point_um": [contact_x, y],
            })
        if net == "VDPWR":
            geometry.wire(
                net, "met4", [min(contacts), y], [spine_x, y],
                float(rules["m4_finger_width_um"]), "row_power_finger",
                f"row_{boundary:02d}_{net}_finger",
            )
        else:
            underpass = plan["ground_finger_underpass"]
            ux0, ux1 = map(float, underpass["x_span_um"])
            geometry.wire(
                net, "met4", [spine_x, y], [ux0, y],
                float(rules["m4_finger_width_um"]), "row_power_finger",
                f"row_{boundary:02d}_{net}_finger_left",
            )
            geometry.via(net, "M3M4", ux0, y, f"row_{boundary:02d}_{net}_underpass_left")
            geometry.wire(
                net, "met3", [ux0, y], [ux1, y],
                float(underpass["width_um"]), "opposite_supply_underpass",
                f"row_{boundary:02d}_{net}_underpass",
            )
            geometry.via(net, "M3M4", ux1, y, f"row_{boundary:02d}_{net}_underpass_right")
            geometry.wire(
                net, "met4", [ux1, y], [max(contacts), y],
                float(rules["m4_finger_width_um"]), "row_power_finger",
                f"row_{boundary:02d}_{net}_finger_right",
            )
        rail_records.append({
            "boundary": boundary,
            "net": net,
            "y_um": y,
            "x_span_um": [x0, extension],
            "upper_contact_count": len(contacts),
        })

    for net, spine in plan["m4_spines"].items():
        spine_x = float(spine["x_um"])
        if "y_span_um" in spine:
            geometry.wire(
                net,
                "met4",
                [spine_x, float(spine["y_span_um"][0])],
                [spine_x, float(spine["y_span_um"][1])],
                float(rules["m4_spine_width_um"]),
                "controller_power_spine",
                f"{net}_controller_spine",
            )
            continue
        lower = list(map(float, spine["lower_y_span_um"]))
        upper = list(map(float, spine["upper_y_span_um"]))
        crossing = list(map(float, spine["metal3_crossing_um"]))
        if lower[1] != crossing[0] or crossing[1] != upper[0]:
            raise ValueError(f"{net} split spine does not meet its crossing")
        geometry.wire(
            net, "met4", [spine_x, lower[0]], [spine_x, lower[1]],
            float(rules["m4_spine_width_um"]), "controller_power_spine",
            f"{net}_controller_spine_lower",
        )
        geometry.wire(
            net, "met3", [spine_x, crossing[0]], [spine_x, crossing[1]],
            float(rules["m3_bridge_width_um"]), "opposite_supply_underpass",
            f"{net}_controller_spine_m3_crossing",
        )
        geometry.via(net, "M3M4", spine_x, crossing[0], f"{net}_spine_lower_via3")
        geometry.via(net, "M3M4", spine_x, crossing[1], f"{net}_spine_upper_via3")
        geometry.wire(
            net, "met4", [spine_x, upper[0]], [spine_x, upper[1]],
            float(rules["m4_spine_width_um"]), "controller_power_spine",
            f"{net}_controller_spine_upper",
        )

    for net, records in plan["source_connections"].items():
        for index, record in enumerate(records):
            owner = f"{net}_source_{index}_{record['role']}"
            geometry.wire(
                net,
                record["layer"],
                record["from_um"],
                record["to_um"],
                float(record["width_um"]),
                "source_connection",
                owner,
            )
            for via_index, point in enumerate(record.get("via3_at_um", [])):
                geometry.via(
                    net,
                    "M3M4",
                    float(point[0]),
                    float(point[1]),
                    f"{owner}_via3_{via_index}",
                )

    geometry.labels = [
        {
            "net": net,
            "gds_label": net,
            "layer": record["layer"],
            "point_um": record["point_um"],
        }
        for net, record in plan["port_labels"].items()
    ]
    geometry.shapes = deduplicate(geometry.shapes)

    label_errors = []
    for label in geometry.labels:
        px, py = map(float, label["point_um"])
        if not any(
            shape["net"] == label["net"]
            and shape["layer"] == label["layer"]
            and shape["bbox_um"][0] - 1e-9 <= px <= shape["bbox_um"][2] + 1e-9
            and shape["bbox_um"][1] - 1e-9 <= py <= shape["bbox_um"][3] + 1e-9
            for shape in geometry.shapes
        ):
            label_errors.append(label)

    minimum_spacing = float(rules["minimum_same_layer_spacing_um"])
    cross_net_spacing_errors: list[dict[str, Any]] = []
    for layer in (*CONDUCTOR_LAYERS, *VIA_ADJACENCY):
        first = [item for item in geometry.shapes if item["net"] == "VDPWR" and item["layer"] == layer]
        second = [item for item in geometry.shapes if item["net"] == "VGND" and item["layer"] == layer]
        for left in first:
            for right in second:
                observed = spacing(left["bbox_um"], right["bbox_um"])
                if observed < minimum_spacing - 1e-9:
                    cross_net_spacing_errors.append({
                        "layer": layer,
                        "spacing_um": observed,
                        "first_owner": left["owner"],
                        "second_owner": right["owner"],
                    })

    structures, database_um = parse_gds(source)
    flattened = flatten_orthogonal_rectangles(
        structures,
        checkpoint["top"],
        database_um,
        {MET1, MET2, MET3, MET4, VIA1, VIA2, VIA3},
    )
    source_overlap_errors: list[dict[str, Any]] = []
    allowed_overlap_prefixes = (
        "VDPWR_source_0_extend_existing_vdpwr_top_trunk",
        "VGND_controller_spine_lower",
    )
    intentional_source_overlaps = [
        {
            "net": record["net"],
            "layer": record["layer"],
            "bbox_um": tuple(map(float, record["bbox_um"])),
        }
        for record in plan["intentional_frozen_overlap_shapes"]
    ]
    for item in geometry.shapes:
        if item["layer"] == "met1":
            continue
        overlaps = [
            source_box
            for source_box in flattened[LAYER_TO_GDS[item["layer"]]]
            if boxes_overlap(item["bbox_um"], source_box)
        ]
        overlap_is_intentional = all(
            any(
                item["net"] == allowed["net"]
                and item["layer"] == allowed["layer"]
                and all(
                    abs(value - expected) < 1e-6
                    for value, expected in zip(source_box, allowed["bbox_um"])
                )
                for allowed in intentional_source_overlaps
            )
            for source_box in overlaps
        )
        if (
            overlaps
            and not item["owner"].startswith(allowed_overlap_prefixes)
            and not overlap_is_intentional
        ):
            source_overlap_errors.append({
                "net": item["net"],
                "layer": item["layer"],
                "owner": item["owner"],
                "bbox_um": item["bbox_um"],
                "source_overlap_count": len(overlaps),
            })

    connectivity = {
        net: connectivity_audit(geometry.shapes, net) for net in ("VDPWR", "VGND")
    }
    errors: list[str] = []
    if any(record["upper_contact_count"] != int(rules["upper_contacts_per_rail"]) for record in rail_records):
        errors.append("a row rail does not have exactly two upper contacts")
    if cross_net_spacing_errors:
        errors.append("VDPWR and VGND violate same-layer spacing")
    if label_errors:
        errors.append(f"power labels miss their own conductor: {label_errors}")
    if source_overlap_errors:
        errors.append("new controller power overlaps frozen non-source geometry")
    for net, audit in connectivity.items():
        if audit["connected_component_count"] != 1:
            errors.append(f"{net} power overlay is not one connected component")
        if audit["orphan_vias"]:
            errors.append(f"{net} contains an orphan via")
    if any(item["layer"] == "met5" for item in geometry.shapes):
        errors.append("Metal 5 is forbidden")

    counts = Counter(item["layer"] for item in geometry.shapes)
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "centralized V3 controller VDPWR/VGND overlay only",
        "source_checkpoint": checkpoint,
        "top": plan["overlay_top"],
        "shapes": geometry.shapes,
        "labels": geometry.labels,
        "rails": rail_records,
        "contacts": contact_records,
        "counts": {
            "shapes": len(geometry.shapes),
            "labels": len(geometry.labels),
            "labels_on_own_conductor": len(geometry.labels) - len(label_errors),
            "rails": len(rail_records),
            "upper_contacts": len(contact_records),
            "by_layer": dict(sorted(counts.items())),
        },
        "connectivity": connectivity,
        "cross_net_spacing_errors": cross_net_spacing_errors,
        "source_overlap_errors": source_overlap_errors,
        "errors": errors,
        "policy": plan["policy"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "v3/layout/physical_control_power_plan.json",
    )
    parser.add_argument(
        "--geometry",
        type=Path,
        default=ROOT / "build/v3/control_power/power_geometry.json",
    )
    parser.add_argument(
        "--overlay-gds",
        type=Path,
        default=ROOT / "build/v3/control_power/direct/v3_ctrl_power_routes.gds",
    )
    parser.add_argument(
        "--output-gds",
        type=Path,
        default=ROOT / "build/v3/control_power/direct/v3_four_channel_ctrl_powered.gds",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "build/v3/control_power/direct/assembly_report.json",
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    source = ROOT / plan["source_checkpoint"]["gds"]
    geometry = generate(plan, source)
    if geometry["status"] != "pass":
        raise SystemExit(json.dumps(geometry["errors"], indent=2))
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(
        json.dumps(geometry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    overlay_report = direct_gds(geometry, source, args.overlay_gds)
    output, assembly = attach_overlay(
        source,
        plan["source_checkpoint"]["top"],
        args.overlay_gds,
        plan["overlay_top"],
        plan["output_top"],
        {"VDPWR", "VGND"},
    )
    args.output_gds.parent.mkdir(parents=True, exist_ok=True)
    args.output_gds.write_bytes(output)
    report = {
        "schema_version": 1,
        "status": "pass",
        "geometry_sha256": sha256(args.geometry),
        "geometry": geometry["counts"],
        "connectivity": geometry["connectivity"],
        "overlay": overlay_report,
        "assembly": assembly,
        "output_gds": str(args.output_gds.relative_to(ROOT)),
        "output_sha256": sha256(args.output_gds),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
