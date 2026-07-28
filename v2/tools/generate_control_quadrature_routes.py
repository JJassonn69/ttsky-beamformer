#!/usr/bin/env python3
"""Generate four compact control-core-to-quadrature-tree routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_phase_routes import DBU, Geometry, bbox, snap
from generate_control_openroad_overlay import direct_gds


def generate(plan: dict[str, Any], allocation: dict[str, Any], root: Path) -> dict[str, Any]:
    source = root / plan["source_checkpoint"]["gds"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_checkpoint"]["sha256"]:
        raise ValueError("quadrature source GDS checkpoint changed")
    allocation_path = root / plan["allocation_checkpoint"]["json"]
    if hashlib.sha256(allocation_path.read_bytes()).hexdigest() != plan["allocation_checkpoint"]["sha256"]:
        raise ValueError("quadrature allocation checkpoint changed")

    openroad_checkpoint = plan["openroad_handoff_checkpoint"]
    openroad_path = root / openroad_checkpoint["geometry"]
    if hashlib.sha256(openroad_path.read_bytes()).hexdigest() != openroad_checkpoint["geometry_sha256"]:
        raise ValueError("quadrature OpenROAD handoff geometry changed")
    openroad = json.loads(openroad_path.read_text(encoding="utf-8"))
    boundary_pins: dict[str, list[float]] = {}
    boundary_pin_boxes: dict[str, list[float]] = {}
    boundary_access_candidates: dict[str, list[list[float]]] = {}
    for shape in openroad["shapes"]:
        if not shape["net"].startswith("phase_wave["):
            continue
        x0, y0, x1, y1 = map(float, shape["bbox_um"])
        if shape["kind"] == "openroad_top_pin":
            boundary_pins[shape["net"]] = [snap((x0 + x1) / 2), snap((y0 + y1) / 2)]
            boundary_pin_boxes[shape["net"]] = [snap(x0), snap(y0), snap(x1), snap(y1)]
        elif shape["kind"] == "openroad_via_M2M3" and shape["layer"] == "met2":
            boundary_access_candidates.setdefault(shape["net"], []).append(
                [snap((x0 + x1) / 2), snap((y0 + y1) / 2)]
            )

    # A routed tree may use several M2/M3 transitions internally.  The analog
    # continuation starts at the lowest transition on that connected routed
    # tree because the analog root lies below the router boundary.  This gives
    # the shortest continuation and avoids depending on DEF segment ordering.
    boundary_accesses: dict[str, list[float]] = {}
    for net in boundary_pins:
        candidates = boundary_access_candidates.get(net, [])
        if not candidates:
            raise ValueError(f"{net}: missing M2/M3 access on routed tree")
        lowest_y = min(point[1] for point in candidates)
        lowest = [point for point in candidates if abs(point[1] - lowest_y) <= 0.01]
        if len(lowest) != 1:
            raise ValueError(
                f"{net}: expected one lowest M2/M3 access, found {len(lowest)}"
            )
        boundary_accesses[net] = lowest[0]

    rules = plan["rules"]
    corridor_overrides = plan.get("metal2_corridor_x_overrides", {})
    manual_boundary_vias = set(plan.get("manual_boundary_via_nets", []))
    records = [item for item in allocation["nets"] if item["class"] == "quadrature_handoff"]
    geometry = Geometry()
    routes: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: item["net"]):
        net = record["net"]
        pins = [item for item in record["endpoints"] if item["kind"] == "standard_cell_pin"]
        roots = [item for item in record["endpoints"] if item["kind"] == "quadrature_root_handoff"]
        drivers = [item for item in pins if item["direction"] == "output"]
        if len(roots) != 1 or len(drivers) != 1:
            raise ValueError(f"{net}: expected one driver and one quadrature root")
        root_x, root_y = map(float, roots[0]["point_um"])
        root_x = snap(root_x)
        if net not in boundary_pins:
            raise ValueError(f"{net}: missing router-owned M3 boundary pin")
        if net not in boundary_accesses and net not in manual_boundary_vias:
            raise ValueError(f"{net}: missing router-owned M2/M3 boundary access")
        pin_x, pin_y = boundary_pins[net]
        if net in manual_boundary_vias:
            boundary_x, boundary_y = pin_x, pin_y
            via2 = float(rules["via2_half_width"])
            m2x = float(rules["metal2_landing_half_x"])
            m2y = float(rules["metal2_landing_half_y"])
            m3 = float(rules["metal3_landing_half_width"])
            geometry.rect(net, "metal2", [boundary_x-m2x, boundary_y-m2y,
                                           boundary_x+m2x, boundary_y+m2y],
                          "manual_boundary_m2")
            geometry.rect(net, "via2", [boundary_x-via2, boundary_y-via2,
                                          boundary_x+via2, boundary_y+via2],
                          "manual_boundary_via2")
            geometry.rect(net, "metal3", [boundary_x-m3, boundary_y-m3,
                                            boundary_x+m3, boundary_y+m3],
                          "manual_boundary_m3")
        else:
            boundary_x, boundary_y = boundary_accesses[net]
        # The complete digital tree, including all LI pin access, is already
        # owned by OpenROAD.  This overlay contains only the monotonic analog
        # continuation from the router-created M2/M3 boundary access to the
        # pre-existing M2 root.  Reusing that via avoids a duplicate cut stack.
        corridor_x = float(corridor_overrides.get(net, boundary_x))
        entry_y = float(plan["corridor_entry_y"])
        if abs(corridor_x-boundary_x) > DBU/2:
            geometry.wire_v(net, "metal2", boundary_x, entry_y, boundary_y,
                            float(rules["metal2_width"]), "boundary_drop")
            geometry.wire_h(net, "metal2", corridor_x, boundary_x, entry_y,
                            float(rules["metal2_width"]), "entry_jog")
            geometry.wire_v(net, "metal2", corridor_x, root_y, entry_y,
                            float(rules["metal2_width"]), "root_column")
        else:
            geometry.wire_v(net, "metal2", corridor_x, root_y, boundary_y,
                            float(rules["metal2_width"]), "root_column")
        if abs(corridor_x-root_x) > DBU/2:
            geometry.wire_h(net, "metal2", root_x, corridor_x, root_y,
                            float(rules["metal2_width"]), "root_jog")
        geometry.labels.append({"net": net, "layer": "metal2",
                                "point_um": [snap(root_x), snap(root_y)]})
        driver = next(item for item in pins if item["direction"] == "output")
        routes.append({
            "net": net,
            "root_um": [snap(root_x), snap(root_y)], "root_interface_layer": "metal2",
            "router_top_pin_um": [pin_x, pin_y],
            "router_top_pin_bbox_um": boundary_pin_boxes[net],
            "router_boundary_access_um": [boundary_x, boundary_y],
            "metal2_corridor_x_um": snap(corridor_x),
            "corridor_entry_y_um": snap(entry_y),
            "driver_instance": driver["instance"], "driver_pin": driver["pin"],
            "mapped_pin_count": len(pins),
            "analog_drop_centerline_um": snap(
                abs(boundary_y-root_y) + abs(boundary_x-corridor_x)
                + abs(corridor_x-root_x)
            ),
            "via_counts": {"viali": 0, "via1": 0,
                           "via2": int(net in manual_boundary_vias)},
            "direction_reversals": int(
                abs(corridor_x-boundary_x) > DBU/2
                and (boundary_x-corridor_x) * (root_x-corridor_x) > 0
            ),
        })

    counts = Counter(item["layer"] for item in geometry.shapes)
    paths = [item["analog_drop_centerline_um"] for item in routes]
    return {
        "schema_version": 1, "units": "um",
        "status": "generated quadrature-root overlay",
        "source_checkpoint": plan["source_checkpoint"],
        "allocation_checkpoint": plan["allocation_checkpoint"],
        "top": plan["overlay_top"], "routes": routes,
        "shapes": geometry.shapes, "labels": geometry.labels,
        "metrics": {"minimum_analog_drop_um": min(paths), "maximum_analog_drop_um": max(paths),
                    "analog_drop_spread_um": snap(max(paths)-min(paths))},
        "counts": {"routes": len(routes), "shapes": len(geometry.shapes),
                   "labels": len(geometry.labels), "by_layer": dict(sorted(counts.items()))},
    }


def magic_tcl(data: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in data["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((f"# {item['id']} {item['net']} {item['kind']}",
                         f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}"))
    for item in data["labels"]:
        x, y = item["point_um"]
        commands.extend((f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
                         f"label {{{item['net']}}} FreeSans 0.10u -met2"))
    body = "\n".join(commands)
    top = data["top"]
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing quadrature_overlay magic]
file mkdir $OUT_DIR
load {top} -silent
select top cell
proc paint_rect {{layer x1 y1 x2 y2}} {{
    box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um
    paint $layer
}}
{body}
select top cell
drc euclidean on
drc style drc(full)
drc check
set count [drc list count total]
puts "CONTROL_QUADRATURE_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "quadrature overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {top}.mag
feedback clear
gds compress 0
gds write {top}.gds
set feedback_count [feedback count]
puts "CONTROL_QUADRATURE_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{
    feedback save quadrature_overlay_gds_feedback.txt
    error "quadrature overlay GDS writer feedback"
}}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_quadrature_route_plan.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/quadrature_geometry.json"))
    parser.add_argument("--tcl", type=Path, default=Path("build/v2/control_routing/generate_quadrature_overlay.tcl"))
    parser.add_argument(
        "--gds", type=Path,
        default=Path(
            "build/v2/control_routing/quadrature_overlay/direct/"
            "v2_control_quad_routes_overlay.gds"
        ),
    )
    parser.add_argument(
        "--gds-report", type=Path,
        default=Path(
            "build/v2/control_routing/quadrature_overlay/direct/gds_write_audit.json"
        ),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    data = generate(json.loads(args.plan.read_text()), json.loads(args.allocation.read_text()), root)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n")
    magic_tcl(data, args.tcl)
    layer_names = {"metal2": "met2", "via2": "via2", "metal3": "met3"}
    gds_data = {
        **data,
        "shapes": [
            {**item, "layer": layer_names[item["layer"]]}
            for item in data["shapes"]
        ],
        "labels": [
            {**item, "layer": layer_names[item["layer"]], "gds_label": item["net"]}
            for item in data["labels"]
        ],
    }
    gds_report = direct_gds(
        gds_data, root / data["source_checkpoint"]["gds"], args.gds
    )
    args.gds_report.parent.mkdir(parents=True, exist_ok=True)
    args.gds_report.write_text(
        json.dumps(gds_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"counts": data["counts"], "metrics": data["metrics"],
                      "gds": gds_report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
