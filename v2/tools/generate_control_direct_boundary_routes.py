#!/usr/bin/env python3
"""Generate the nine compact phase-bank/global-core boundary routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_phase_routes import DBU, Geometry, snap


def generate(
    plan: dict[str, Any], allocation: dict[str, Any], catalog: dict[str, Any], root: Path
) -> dict[str, Any]:
    for key, field in (("source_checkpoint", "gds"), ("allocation_checkpoint", "json"), ("pin_access_checkpoint", "json"), ("service_access_checkpoint", "json")):
        path = root / plan[key][field]
        if hashlib.sha256(path.read_bytes()).hexdigest() != plan[key]["sha256"]:
            raise ValueError(f"{key} changed")
    records = {item["net"]: item for item in allocation["nets"] if item["class"] == "direct_boundary"}
    if set(records) != set(plan["routes"]):
        raise ValueError("direct-boundary route set differs from allocation")
    accesses = {(item["instance"], item["pin"]): item for item in catalog["records"]}
    rules = plan["rules"]
    li_overrides = plan.get("locali_access_overrides", {})
    access_overrides = plan.get("metal2_access_overrides", {})
    leaf_overrides = plan.get("leaf_column_x_overrides", {})
    geometry = Geometry()
    routes: list[dict[str, Any]] = []

    for net, route_plan in sorted(plan["routes"].items()):
        record = records[net]
        spine_x = float(route_plan["spine_x_um"])
        phase_y = float(route_plan["phase_track_y_um"])
        global_y = float(route_plan["global_track_y_um"])
        route_accesses: list[dict[str, Any]] = []
        by_region: dict[str, list[float]] = {"phase_configuration_bank": [], "global_control_core": []}

        for endpoint in record["endpoints"]:
            if endpoint["kind"] != "standard_cell_pin":
                raise ValueError(f"{net}: unexpected endpoint kind {endpoint['kind']}")
            key = (endpoint["instance"], endpoint["pin"])
            access_record = accesses.get(key)
            if access_record is None or access_record["net"] != net:
                raise ValueError(f"{net}: missing catalog access for {key}")
            selected = access_record["selected_access"]
            if selected["layer"] != "li1" or not selected["inside_inset_lef_port"]:
                raise ValueError(f"{net}: {key} is not a legal LI access")
            override_key = f"{endpoint['instance']}|{endpoint['pin']}"
            pin_x, pin_y = map(float, li_overrides.get(override_key, selected["point_um"]))
            legal_override = any(
                item["layer"] == "li1"
                and item["rect_um"][0] + item["required_inset_um"] <= pin_x + 1e-9
                and pin_x <= item["rect_um"][2] - item["required_inset_um"] + 1e-9
                and item["rect_um"][1] + item["required_inset_um"] <= pin_y + 1e-9
                and pin_y <= item["rect_um"][3] - item["required_inset_um"] + 1e-9
                for item in access_record["legal_access_rects"]
            )
            if not legal_override:
                raise ValueError(f"{net}: {key} override is outside the inset LEF port")
            point_x, point_y = map(float, endpoint["point_um"])
            if override_key not in li_overrides and (abs(pin_x-point_x) > DBU/2+1e-9 or abs(pin_y-point_y) > DBU/2+1e-9):
                raise ValueError(f"{net}: allocation/catalog access mismatch for {key}")
            access_x, access_y = map(float, access_overrides.get(override_key, [pin_x, pin_y]))
            leaf_x = float(leaf_overrides.get(override_key, access_x))
            track_y = phase_y if endpoint["region"] == "phase_configuration_bank" else global_y
            by_region[endpoint["region"]].append(leaf_x)

            li = float(rules["locali_half_width"])
            m1 = float(rules["metal1_pad_half_width"])
            v1 = float(rules["via1_half_width"])
            m2 = float(rules["metal2_landing_half_width"])
            v2 = float(rules["via2_half_width"])
            m3x = float(rules["metal3_landing_half_x"])
            m3y = float(rules["metal3_landing_half_y"])
            geometry.rect(net, "locali", [pin_x-li, pin_y-li, pin_x+li, pin_y+li], "pin_li")
            geometry.rect(net, "viali", [pin_x-li, pin_y-li, pin_x+li, pin_y+li], "pin_viali")
            geometry.rect(net, "metal1", [pin_x-m1, pin_y-m1, pin_x+m1, pin_y+m1], "pin_m1")
            escaped_on_m1 = abs(access_x-pin_x) > DBU/2 or abs(access_y-pin_y) > DBU/2
            if abs(access_x-pin_x) > DBU/2:
                geometry.wire_h(net, "metal1", pin_x, access_x, pin_y, float(rules["metal1_width"]), "access_escape")
            if abs(access_y-pin_y) > DBU/2:
                geometry.wire_v(net, "metal1", access_x, pin_y, access_y, float(rules["metal1_width"]), "access_escape")
            if escaped_on_m1:
                geometry.rect(net, "metal1", [access_x-m1, access_y-m1, access_x+m1, access_y+m1], "escape_m1")
            geometry.rect(net, "via1", [access_x-v1, access_y-v1, access_x+v1, access_y+v1], "pin_via1")
            geometry.rect(net, "metal2", [access_x-m2, access_y-m2, access_x+m2, access_y+m2], "pin_m2")
            if abs(leaf_x-access_x) > DBU/2:
                geometry.wire_h(net, "metal2", access_x, leaf_x, access_y, float(rules["metal2_width"]), "pin_escape")
            geometry.wire_v(net, "metal2", leaf_x, access_y, track_y, float(rules["metal2_width"]), "pin_leaf")
            geometry.rect(net, "metal2", [leaf_x-v2, track_y-v2, leaf_x+v2, track_y+v2], "leaf_via2_m2")
            geometry.rect(net, "via2", [leaf_x-v2, track_y-v2, leaf_x+v2, track_y+v2], "leaf_via2")
            geometry.rect(net, "metal3", [leaf_x-m3x, track_y-m3y, leaf_x+m3x, track_y+m3y], "leaf_via2_m3")
            route_accesses.append({
                "instance": endpoint["instance"], "cell": endpoint["cell"], "pin": endpoint["pin"],
                "direction": endpoint["direction"], "region": endpoint["region"],
                "pin_um": [snap(pin_x), snap(pin_y)], "metal2_access_um": [snap(access_x), snap(access_y)],
                "leaf_x_um": snap(leaf_x),
                "track_y_um": snap(track_y), "catalog_legal": True,
                "pin_escape_um": snap(abs(access_x-pin_x)+abs(access_y-pin_y)+abs(leaf_x-access_x)),
            })

        v2 = float(rules["via2_half_width"])
        m3x = float(rules["metal3_landing_half_x"])
        m3y = float(rules["metal3_landing_half_y"])
        geometry.wire_v(net, "metal2", spine_x, phase_y, global_y, float(rules["metal2_width"]), "boundary_spine")
        for region, track_y in (("phase_configuration_bank", phase_y), ("global_control_core", global_y)):
            geometry.rect(net, "metal2", [spine_x-v2, track_y-v2, spine_x+v2, track_y+v2], "spine_via2_m2")
            geometry.rect(net, "via2", [spine_x-v2, track_y-v2, spine_x+v2, track_y+v2], "spine_via2")
            geometry.rect(net, "metal3", [spine_x-m3x, track_y-m3y, spine_x+m3x, track_y+m3y], "spine_via2_m3")
            xs = by_region[region] + [spine_x]
            geometry.wire_h(net, "metal3", min(xs), max(xs), track_y, float(rules["metal3_width"]), f"{region}_trunk")

        drivers = [item for item in route_accesses if item["direction"] == "output"]
        if len(drivers) != 1:
            raise ValueError(f"{net}: expected one driver, found {len(drivers)}")
        driver = drivers[0]
        geometry.labels.append({"net": net, "layer": "metal2", "point_um": driver["metal2_access_um"]})
        pin_leaf_length = sum(abs(item["metal2_access_um"][1]-item["track_y_um"]) + item["pin_escape_um"] for item in route_accesses)
        trunk_length = sum(max(by_region[region] + [spine_x])-min(by_region[region] + [spine_x]) for region in by_region)
        routes.append({
            "net": net, "spine_x_um": snap(spine_x),
            "phase_track_y_um": snap(phase_y), "global_track_y_um": snap(global_y),
            "mapped_pin_count": len(route_accesses), "accesses": route_accesses,
            "driver_instance": driver["instance"], "driver_pin": driver["pin"],
            "total_centerline_um": snap(pin_leaf_length + trunk_length + abs(global_y-phase_y)),
            "maximum_pin_escape_um": max(item["pin_escape_um"] for item in route_accesses),
            "via_counts": {"viali": len(route_accesses), "via1": len(route_accesses), "via2": len(route_accesses)+2},
            "direction_reversals": 0,
        })

    counts = Counter(item["layer"] for item in geometry.shapes)
    return {
        "schema_version": 1, "units": "um", "status": "generated direct-boundary overlay",
        "source_checkpoint": plan["source_checkpoint"], "allocation_checkpoint": plan["allocation_checkpoint"],
        "pin_access_checkpoint": plan["pin_access_checkpoint"],
        "service_access_checkpoint": plan["service_access_checkpoint"],
        "top": plan["overlay_top"],
        "routes": routes, "shapes": geometry.shapes, "labels": geometry.labels,
        "counts": {"routes": len(routes), "shapes": len(geometry.shapes), "labels": len(geometry.labels), "by_layer": dict(sorted(counts.items()))},
        "metrics": {"total_centerline_um": snap(sum(item["total_centerline_um"] for item in routes)),
                    "maximum_pin_escape_um": max(item["maximum_pin_escape_um"] for item in routes)},
    }


def magic_tcl(data: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in data["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((f"# {item['id']} {item['net']} {item['kind']}", f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}"))
    for item in data["labels"]:
        x, y = item["point_um"]
        commands.extend((f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um", f"label {{{item['net']}}} FreeSans 0.10u -met2"))
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing direct_boundary_overlay]
file mkdir $OUT_DIR
load {data['top']} -silent
select top cell
proc paint_rect {{layer x1 y1 x2 y2}} {{
    box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um
    paint $layer
}}
{chr(10).join(commands)}
select top cell
drc euclidean on
drc style drc(full)
drc check
set count [drc list count total]
puts "CONTROL_DIRECT_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "direct-boundary overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {data['top']}.mag
feedback clear
gds compress 0
gds write {data['top']}.gds
set feedback_count [feedback count]
puts "CONTROL_DIRECT_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{
    feedback save direct_boundary_overlay_gds_feedback.txt
    error "direct-boundary overlay GDS writer feedback"
}}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_direct_boundary_route_plan.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--catalog", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/direct_boundary_geometry.json"))
    parser.add_argument("--tcl", type=Path, default=Path("build/v2/control_routing/generate_direct_boundary_overlay.tcl"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    data = generate(json.loads(args.plan.read_text()), json.loads(args.allocation.read_text()), json.loads(args.catalog.read_text()), root)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    magic_tcl(data, args.tcl)
    print(json.dumps({"counts": data["counts"], "metrics": data["metrics"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
