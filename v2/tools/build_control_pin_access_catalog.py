#!/usr/bin/env python3
"""Build exact, orientation-aware legal access regions for every control pin.

The placement JSON intentionally stores one convenient point per pin. A
production router needs the complete transformed LEF geometry so that an
escape cannot accidentally leave the named pin and land on an internal node.
This catalog is the frozen interface between placement and signal routing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


GRID = 0.005
POWER_PINS = {"VGND", "VPWR", "VPB", "VNB"}
ACCESS_MARGIN = {"li1": 0.085, "met1": 0.0, "met2": 0.0}
SERVICE_LIFT_MARGIN = {"li1": 0.085, "met1": 0.13, "met2": 0.20}
SERVICE_SEARCH_PITCH = 0.115


def snap(value: float) -> float:
    return round(round(value / GRID) * GRID, 6)


def transform_rect(
    rect: list[float], width: float, height: float, orientation: str
) -> list[float]:
    x0, y0, x1, y1 = map(float, rect)
    if orientation == "R0":
        result = [x0, y0, x1, y1]
    elif orientation == "MX":
        result = [x0, height - y1, x1, height - y0]
    elif orientation == "MY":
        result = [width - x1, y0, width - x0, y1]
    elif orientation == "R180":
        result = [width - x1, height - y1, width - x0, height - y0]
    else:
        raise ValueError(f"unsupported standard-cell orientation {orientation}")
    return [snap(value) for value in result]


def contains(rect: list[float], point: list[float], margin: float = 0.0) -> bool:
    x0, y0, x1, y1 = rect
    x, y = point
    return (
        x0 + margin <= x + 1e-9
        and x <= x1 - margin + 1e-9
        and y0 + margin <= y + 1e-9
        and y <= y1 - margin + 1e-9
    )


def candidate_points(rect: list[float], margin: float) -> list[list[float]]:
    x0, y0, x1, y1 = rect
    lo_x, hi_x = snap(x0 + margin), snap(x1 - margin)
    lo_y, hi_y = snap(y0 + margin), snap(y1 - margin)
    if lo_x > hi_x + 1e-9 or lo_y > hi_y + 1e-9:
        return []
    cx, cy = snap((lo_x + hi_x) / 2.0), snap((lo_y + hi_y) / 2.0)
    ordered = ([cx, cy], [lo_x, cy], [hi_x, cy], [cx, lo_y], [cx, hi_y])
    result: list[list[float]] = []
    for point in ordered:
        if point not in result and contains(rect, point, margin):
            result.append(point)
    return result


def service_candidate_points(rect: list[float], margin: float) -> list[list[float]]:
    """Enumerate dense, deterministic via candidates inside one LEF port."""

    x0, y0, x1, y1 = rect
    lo_x, hi_x = snap(x0 + margin), snap(x1 - margin)
    lo_y, hi_y = snap(y0 + margin), snap(y1 - margin)
    if lo_x > hi_x + 1e-9 or lo_y > hi_y + 1e-9:
        return []
    xs = {lo_x, hi_x, snap((lo_x + hi_x) / 2.0)}
    ys = {lo_y, hi_y, snap((lo_y + hi_y) / 2.0)}
    step = 0
    while lo_x + step * SERVICE_SEARCH_PITCH < hi_x - 1e-9:
        xs.add(snap(lo_x + step * SERVICE_SEARCH_PITCH))
        step += 1
    step = 0
    while lo_y + step * SERVICE_SEARCH_PITCH < hi_y - 1e-9:
        ys.add(snap(lo_y + step * SERVICE_SEARCH_PITCH))
        step += 1
    center_x, center_y = (lo_x + hi_x) / 2.0, (lo_y + hi_y) / 2.0
    return sorted(
        ([x, y] for x in xs for y in ys if contains(rect, [x, y], margin)),
        key=lambda point: (
            abs(point[0] - center_x) + abs(point[1] - center_y),
            abs(point[1] - center_y), abs(point[0] - center_x),
            point[1], point[0],
        ),
    )


def build(mapping: dict[str, Any], placement: dict[str, Any], root: Path) -> dict[str, Any]:
    cells = {item["instance"]: item for item in mapping["cells"]}
    placed = {item["instance"]: item for item in placement["placements"]}
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    for instance, cell in sorted(cells.items()):
        if instance not in placed:
            errors.append(f"{instance}: missing placement")
            continue
        placed_cell = placed[instance]
        spec = mapping["library"][cell["short_cell"]]
        width, height = map(float, spec["size_um"])
        origin_x, origin_y = map(float, placed_cell["origin_um"])
        orientation = placed_cell["orientation"]
        selected = placed_cell["pin_access"]
        for pin, net in sorted(cell["pins"].items()):
            if pin in POWER_PINS:
                continue
            access = selected.get(pin)
            if access is None:
                errors.append(f"{instance}.{pin}: placement has no selected access")
                continue
            transformed: list[dict[str, Any]] = []
            for index, raw in enumerate(spec["pins"][pin]["access_rects"]):
                local = transform_rect(raw["rect_um"], width, height, orientation)
                absolute = [
                    snap(local[0] + origin_x), snap(local[1] + origin_y),
                    snap(local[2] + origin_x), snap(local[3] + origin_y),
                ]
                margin = ACCESS_MARGIN.get(raw["layer"], 0.0)
                candidates = candidate_points(absolute, margin)
                if candidates:
                    service_margin = SERVICE_LIFT_MARGIN.get(raw["layer"], margin)
                    transformed.append({
                        "port_rect_index": index,
                        "layer": raw["layer"],
                        "rect_um": absolute,
                        "required_inset_um": margin,
                        "candidate_points_um": candidates,
                        "service_required_inset_um": service_margin,
                        "service_candidate_points_um": service_candidate_points(
                            absolute, service_margin
                        ),
                    })
            selected_point = list(map(float, access["point_um"]))
            selected_layer = access["layer"]
            legal = any(
                item["layer"] == selected_layer
                and contains(item["rect_um"], selected_point, item["required_inset_um"])
                for item in transformed
            )
            if not legal:
                errors.append(
                    f"{instance}.{pin}: selected {selected_layer} access "
                    f"{selected_point} is outside every inset LEF port rectangle"
                )
            records.append({
                "instance": instance,
                "cell": cell["cell"],
                "short_cell": cell["short_cell"],
                "pin": pin,
                "direction": spec["pins"][pin]["direction"],
                "net": net,
                "region": placed_cell["region"],
                "row": placed_cell["row"],
                "orientation": orientation,
                "selected_access": {
                    "layer": selected_layer,
                    "point_um": [snap(value) for value in selected_point],
                    "inside_inset_lef_port": legal,
                },
                "legal_access_rects": transformed,
            })

    mapping_path = root / "build/v2/control_mapping/physical_netlist.json"
    placement_path = root / "build/v2/control_placement/control_placement.json"
    return {
        "schema_version": 1,
        "units": "um",
        "status": "pass" if not errors else "fail",
        "policy": {
            "coordinates_are_orientation_transformed": True,
            "li1_candidate_keeps_full_viali_cut_inside_named_pin": True,
            "met1_service_candidate_keeps_full_via1_landing_inside_named_pin": True,
            "service_candidates_are_densely_enumerated_for_exact_m1_obstacle_search": True,
            "router_must_use_a_catalog_candidate_or_prove_an_override": True,
            "route_to_raw_pin_center_without_port_containment_check": False,
        },
        "source_sha256": {
            "mapping": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
            "placement": hashlib.sha256(placement_path.read_bytes()).hexdigest(),
        },
        "record_count": len(records),
        "errors": errors,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--placement", type=Path, default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--output", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = build(json.loads(args.mapping.read_text()), json.loads(args.placement.read_text()), root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "record_count", "errors")}, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
