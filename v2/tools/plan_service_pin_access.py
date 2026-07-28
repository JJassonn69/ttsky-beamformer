#!/usr/bin/env python3
"""Freeze one exact lower-metal landing for every future service-tree pin.

This floorplanning step intentionally runs before the direct-boundary routes.
The resulting M2 boxes are hard keepouts for that later stage, while the final
service router is required to use the same named LEF-port access points.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_phase_routes import snap
from generate_control_service_routes import (
    _source_index, allocate_row_tracks, branch_key, choose_pin_escape,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET1, flatten_orthogonal_rectangles, flatten_rectangles, parse_gds,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(source_plan: dict[str, Any], service_plan: dict[str, Any],
             allocation: dict[str, Any], catalog: dict[str, Any],
             direct_geometry: dict[str, Any], root: Path) -> dict[str, Any]:
    """Select direct-via service landings against the pre-direct exact GDS."""
    source_checkpoint = source_plan["source_checkpoint"]
    for checkpoint, field in (
        (source_checkpoint, "gds"),
        (source_plan["allocation_checkpoint"], "json"),
        (source_plan["pin_access_checkpoint"], "json"),
    ):
        path = root / checkpoint[field]
        if _sha256(path) != checkpoint["sha256"]:
            raise ValueError(f"checkpoint changed: {path}")

    if source_plan["allocation_checkpoint"] != service_plan["allocation_checkpoint"]:
        raise ValueError("direct and service plans do not share the allocation checkpoint")
    if source_plan["pin_access_checkpoint"] != service_plan["pin_access_checkpoint"]:
        raise ValueError("direct and service plans do not share the pin-access checkpoint")

    structures, database_um = parse_gds(root / source_checkpoint["gds"])
    rectangles = flatten_rectangles(
        structures, source_checkpoint["top"], database_um
    )
    rectangles[MET1] = flatten_orthogonal_rectangles(
        structures, source_checkpoint["top"], database_um, {MET1}
    )[MET1]
    source = _source_index(rectangles)

    rules = service_plan["rules"]
    catalog_by_key = {
        (item["instance"], item["pin"]): item for item in catalog["records"]
    }
    records = {
        item["net"]: item for item in allocation["nets"]
        if item["class"] == "service_tree"
    }
    row_tracks = allocate_row_tracks(service_plan, records)
    endpoints = [
        (record["net"], endpoint)
        for record in allocation["nets"] if record["class"] == "service_tree"
        for endpoint in record["endpoints"]
        if endpoint.get("kind") == "standard_cell_pin"
    ]
    endpoints.sort(key=lambda item: (
        item[0], item[1]["region"], int(item[1]["row"]),
        float(item[1]["point_um"][0]), item[1]["instance"], item[1]["pin"],
    ))

    # These long resources are painted before local service escapes in the
    # real generator, so they must participate in the same selection here.
    service_planned: list[dict[str, Any]] = []
    m3_half = float(rules["metal3_width"]) / 2
    y0, y1 = map(float, service_plan["spine_y_range"])
    for net, x_raw in sorted(service_plan["spines"].items()):
        x = float(x_raw)
        service_planned.append({
            "net": net, "layer": "metal3",
            "bbox_um": [x-m3_half, y0, x+m3_half, y1],
        })
    for x_raw in service_plan["ground_shields_x"]:
        x = float(x_raw)
        service_planned.append({
            "net": "VGND", "layer": "metal3",
            "bbox_um": [x-m3_half, y0, x+m3_half, y1],
        })
    reservations: list[dict[str, Any]] = []
    direct_obstacles = [
        {
            "net": item["net"], "layer": item["layer"],
            "bbox_um": list(map(float, item["bbox_um"])),
        }
        for item in direct_geometry["shapes"]
        if item["layer"] in ("metal1", "metal2", "metal3")
    ]
    tentative_direct_conflicts = 0
    for net, endpoint in endpoints:
        key = (endpoint["instance"], endpoint["pin"])
        record = catalog_by_key.get(key)
        if record is None or record["net"] != net:
            raise ValueError(f"{net}: missing catalog record for {key}")
        _region, _group, track_y = branch_key(
            service_plan, net, endpoint, row_tracks
        )
        direct_conflict = False
        try:
            selected = choose_pin_escape(
                net, endpoint, record, track_y, service_plan, source,
                direct_obstacles + service_planned,
            )
        except ValueError:
            # There is no alternate service escape around the provisional
            # boundary route.  Freeze the best pre-direct escape and let the
            # hard keepout audit identify which boundary segment must move.
            selected = choose_pin_escape(
                net, endpoint, record, track_y, service_plan, source,
                service_planned,
            )
            direct_conflict = True
            tentative_direct_conflicts += 1
        x, y = map(float, selected["pin_um"])
        m1_box = next(
            box for layer, box, kind in selected["boxes"]
            if layer == "metal1" and kind == "pin_m1"
        )
        m2_box = next(
            box for layer, box, kind in selected["boxes"]
            if layer == "metal2" and kind == "lift_m2"
        )
        reserved_shapes = [
            {
                "layer": layer,
                "bbox_um": [snap(value) for value in box],
                "kind": kind,
            }
            for layer, box, kind in selected["boxes"]
        ]
        reservation = {
            "net": net,
            "instance": endpoint["instance"],
            "cell": endpoint["cell"],
            "pin": endpoint["pin"],
            "direction": endpoint["direction"],
            "region": endpoint["region"],
            "row": int(endpoint["row"]),
            "pin_layer": selected["pin_layer"],
            "pin_um": [snap(x), snap(y)],
            "lift_um": selected["lift_um"],
            "leaf_x_um": selected["leaf_x_um"],
            "via2_um": selected["via2_um"],
            "leaf_topology": selected["leaf_topology"],
            "bend_order": selected["bend_order"],
            "m1_escape_manhattan_um": selected["m1_escape_manhattan_um"],
            "m2_leaf_escape_um": selected["m2_leaf_escape_um"],
            "m1_bbox_um": [snap(value) for value in m1_box],
            "m2_keepout_bbox_um": [snap(value) for value in m2_box],
            "reserved_shapes": reserved_shapes,
            "zero_lateral_m1": True,
            "tentative_direct_conflict": direct_conflict,
        }
        reservations.append(reservation)
        service_planned.extend(
            {"net": net, "layer": item["layer"], "bbox_um": item["bbox_um"]}
            for item in reserved_shapes
        )

    layer_counts = Counter(item["pin_layer"] for item in reservations)
    return {
        "schema_version": 1,
        "units": "um",
        "status": "frozen pre-direct service-pin access contract",
        "source_checkpoint": source_checkpoint,
        "allocation_checkpoint": source_plan["allocation_checkpoint"],
        "pin_access_checkpoint": source_plan["pin_access_checkpoint"],
        "policy": {
            "selection_stage": "after quadrature routing and before direct-boundary routing",
            "m1_escape": "zero lateral M1; one via1 is centered inside the named LEF port",
            "direct_route_obligation": "all reserved M1/M2/M3 local escape shapes plus clearance are hard keepouts",
            "service_route_obligation": "the final service router must reproduce these exact local escapes",
        },
        "reservation_count": len(reservations),
        "selected_access_layer_count": dict(sorted(layer_counts.items())),
        "tentative_direct_conflict_count": tentative_direct_conflicts,
        "tentative_direct_geometry_shape_sha256": hashlib.sha256(
            json.dumps(
                direct_geometry["shapes"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "reservations": reservations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-plan", type=Path,
        default=Path("v2/layout/control_direct_boundary_route_plan.json"),
    )
    parser.add_argument(
        "--service-plan", type=Path,
        default=Path("v2/layout/control_service_route_plan.json"),
    )
    parser.add_argument(
        "--allocation", type=Path,
        default=Path("build/v2/control_routing/control_route_allocation.json"),
    )
    parser.add_argument(
        "--catalog", type=Path,
        default=Path("build/v2/control_routing/control_pin_access_catalog.json"),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v2/control_routing/service_pin_access_reservations.json"),
    )
    parser.add_argument(
        "--direct-geometry", type=Path,
        default=Path("build/v2/control_routing/direct_boundary_geometry.json"),
    )
    args = parser.parse_args()
    data = generate(
        json.loads(args.source_plan.read_text()),
        json.loads(args.service_plan.read_text()),
        json.loads(args.allocation.read_text()),
        json.loads(args.catalog.read_text()),
        json.loads(args.direct_geometry.read_text()),
        ROOT,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: data[key] for key in (
        "status", "reservation_count", "selected_access_layer_count",
        "tentative_direct_conflict_count",
    )}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
