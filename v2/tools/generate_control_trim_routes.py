#!/usr/bin/env python3
"""Generate the sixteen monotonic control-core-to-analog trim handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_openroad_overlay import direct_gds


TOP = "v2_control_trim_routes_overlay"
M2_WIDTH = 0.32
M3_WIDTH = 0.40


class Geometry:
    def __init__(self) -> None:
        self.shapes: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []
        self.serial = 0

    def rect(
        self, net: str, layer: str, bbox: list[float], kind: str, owner: str
    ) -> None:
        x0, y0, x1, y1 = map(float, bbox)
        self.serial += 1
        self.shapes.append({
            "id": f"TRIM_{self.serial:04d}",
            "net": net,
            "layer": layer,
            "bbox_um": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
            "kind": kind,
            "owner": owner,
        })

    def wire_h(
        self, net: str, layer: str, x0: float, x1: float, y: float,
        width: float, kind: str, owner: str,
    ) -> None:
        self.rect(net, layer, [x0, y - width / 2, x1, y + width / 2], kind, owner)

    def wire_v(
        self, net: str, layer: str, x: float, y0: float, y1: float,
        width: float, kind: str, owner: str,
    ) -> None:
        self.rect(net, layer, [x - width / 2, y0, x + width / 2, y1], kind, owner)

    def via2(
        self, net: str, point: list[float], owner: str,
        *, m3_right_edge: float | None = None,
    ) -> None:
        x, y = map(float, point)
        # Exact SKY130 M2M3 single-cut geometry used by the audited OpenROAD
        # overlay.  The compact 0.33 um M3 landing is required for the 0.64 um
        # trim-row pitch; the previous generic 0.40 um landing was overbuilt.
        self.rect(net, "metal2", [x - .14, y - .185, x + .14, y + .185],
                  "via2_m2_landing", owner)
        self.rect(net, "via2", [x - .10, y - .10, x + .10, y + .10],
                  "via2_cut", owner)
        # Router handoff pins have 0.30 um height.  The legal 0.20 um cut
        # requires 0.065 um M3 enclosure, so the landing protrudes by 15 nm.
        # Extend that landing toward the already-connected OpenROAD M3 via to
        # close the same-net notch seen on one trim row.  Sink landings remain
        # compact to protect row-to-row clearance and analog capacitance.
        right = x + .165 if m3_right_edge is None else float(m3_right_edge)
        if right < x + .165 - 1e-9:
            raise ValueError(f"{net}: M3 bridge truncates the legal via landing")
        self.rect(net, "metal3", [x - .165, y - .165, right, y + .165],
                  "via2_m3_landing", owner)


def generate(
    plan: dict[str, Any], allocation: dict[str, Any], root: Path
) -> dict[str, Any]:
    source = root / plan["source_checkpoint"]["gds"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_checkpoint"]["sha256"]:
        raise ValueError("trim source GDS checkpoint changed")
    allocation_path = root / plan["allocation_checkpoint"]["json"]
    if hashlib.sha256(allocation_path.read_bytes()).hexdigest() != plan["allocation_checkpoint"]["sha256"]:
        raise ValueError("trim allocation checkpoint changed")
    handoff_checkpoint = plan["openroad_handoff_checkpoint"]
    jobs_path = root / handoff_checkpoint["jobs"]
    geometry_path = root / handoff_checkpoint["geometry"]
    if hashlib.sha256(jobs_path.read_bytes()).hexdigest() != handoff_checkpoint["jobs_sha256"]:
        raise ValueError("trim OpenROAD job checkpoint changed")
    if hashlib.sha256(geometry_path.read_bytes()).hexdigest() != handoff_checkpoint["geometry_sha256"]:
        raise ValueError("trim OpenROAD geometry checkpoint changed")
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    trim_job = next(
        item for item in jobs["jobs"]
        if sum(pin.startswith("T") for pin in item["top_pins"]) == 16
    )
    offset_x, offset_y = map(float, trim_job["coordinate_offset_um"])
    handoff_by_net = {
        item["net"]: {
            "pin": pin,
            "layer": item["layer"],
            "point_um": [
                float(item["point_um"][0]) + offset_x,
                float(item["point_um"][1]) + offset_y,
            ],
        }
        for pin, item in trim_job["top_pins"].items()
    }
    geometry = Geometry()
    routes: list[dict[str, Any]] = []
    for record in allocation["nets"]:
        if record["class"] != "trim_handoff":
            continue
        net = record["net"]
        pins = [item for item in record["endpoints"] if item["kind"] == "standard_cell_pin"]
        anchors = [item for item in record["endpoints"] if item["kind"] == "trim_bus_handoff"]
        drivers = [item for item in pins if item["direction"] == "output"]
        sinks = [item for item in pins if item["direction"] == "input"]
        if len(drivers) != 1 or len(sinks) != 1 or len(anchors) != 1:
            raise ValueError(
                f"{net}: expected one driver, one feedback sink, and one handoff anchor"
            )
        driver, sink, anchor = drivers[0], sinks[0], anchors[0]
        ax, ay = map(float, anchor["point_um"])
        sink_x, sink_y = map(float, anchor["sink_point_um"])
        handoff = handoff_by_net.get(net)
        if handoff is None or handoff["layer"] != "met3":
            raise ValueError(f"{net}: missing frozen OpenROAD M3 handoff pin")
        handoff_x, handoff_y = map(float, handoff["point_um"])
        if abs(handoff_y - ay) > 1e-9:
            raise ValueError(f"{net}: OpenROAD handoff row differs from trim allocation")
        owner = net

        geometry.via2(
            net, [handoff_x, handoff_y],
            f"{net}:router_handoff_transition",
            m3_right_edge=plan.get("router_m3_bridge_right_edge_um", {}).get(net),
        )
        geometry.wire_h(net, "metal2", sink_x, handoff_x, handoff_y, M2_WIDTH,
                        "monotonic_trim_bus", owner)
        geometry.via2(net, [sink_x, handoff_y], f"{net}:analog_sink_transition")
        geometry.wire_v(net, "metal3", sink_x, handoff_y, sink_y, M3_WIDTH,
                        "analog_sink_rise", owner)
        geometry.labels.append({
            "net": net,
            "layer": "metal2",
            "point_um": [handoff_x, handoff_y],
            "owner": owner,
        })
        routes.append({
            "net": net,
            "driver": {"instance": driver["instance"], "pin": driver["pin"],
                       "point_um": driver["point_um"]},
            "feedback_sink": {"instance": sink["instance"], "pin": sink["pin"],
                              "point_um": sink["point_um"]},
            "openroad_handoff_pin": handoff["pin"],
            "openroad_handoff_um": [handoff_x, handoff_y],
            "anchor_um": [ax, ay],
            "analog_sink_um": [sink_x, sink_y],
            "m3_column_x_um": sink_x,
            "m3_length_um": abs(sink_y - handoff_y),
            "m2_length_um": abs(handoff_x - sink_x),
            "direction_reversals": 0,
            "via_counts": {"viali": 0, "via1": 0, "via2": 2},
        })

    layer_counts = Counter(item["layer"] for item in geometry.shapes)
    if len(routes) != int(plan["expected_route_count"]):
        raise ValueError(
            f"generated {len(routes)} trim routes, expected {plan['expected_route_count']}"
        )
    return {
        "schema_version": 1,
        "units": "um",
        "status": "generated trim-handoff route overlay",
        "source_checkpoint": plan["source_checkpoint"],
        "allocation_checkpoint": plan["allocation_checkpoint"],
        "openroad_handoff_checkpoint": plan["openroad_handoff_checkpoint"],
        "top": plan["overlay_top"],
        "source_allocation_status": allocation["status"],
        "routes": routes,
        "shapes": geometry.shapes,
        "labels": geometry.labels,
        "counts": {
            "routes": len(routes),
            "labels": len(geometry.labels),
            "shapes": len(geometry.shapes),
            "by_layer": dict(sorted(layer_counts.items())),
        },
    }


def magic_tcl(geometry: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in geometry["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((
            f"# {item['id']} {item['net']} {item['kind']}",
            f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}",
        ))
    for item in geometry["labels"]:
        x, y = item["point_um"]
        commands.extend((
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{{item['net']}}} FreeSans 0.10u -met2",
        ))
    body = "\n".join(commands)
    text = f"""# Generated by v2/tools/generate_control_trim_routes.py; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing trim_overlay magic]
file mkdir $OUT_DIR
load {TOP} -silent
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
set drc_count [drc list count total]
puts "CONTROL_TRIM_OVERLAY_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR control_trim_overlay_drc.txt]
    error "refusing trim route overlay with $drc_count DRC errors"
}}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {TOP}.mag
puts "CONTROL_TRIM_OVERLAY_PREVIEW_ONLY=1"
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path,
        default=Path("v2/layout/control_trim_route_plan.json"),
    )
    parser.add_argument("--allocation", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_routing/trim_geometry.json"))
    parser.add_argument("--tcl", type=Path,
                        default=Path("build/v2/control_routing/generate_trim_overlay.tcl"))
    parser.add_argument(
        "--gds", type=Path,
        default=Path(
            "build/v2/control_routing/trim_overlay/direct/"
            "v2_control_trim_routes_overlay.gds"
        ),
    )
    parser.add_argument(
        "--gds-report", type=Path,
        default=Path(
            "build/v2/control_routing/trim_overlay/direct/gds_write_audit.json"
        ),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = generate(
        json.loads(args.plan.read_text()),
        json.loads(args.allocation.read_text()),
        root,
    )
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    magic_tcl(result, args.tcl)
    layer_names = {
        "locali": "li1",
        "viali": "mcon",
        "metal1": "met1",
        "via1": "via",
        "metal2": "met2",
        "via2": "via2",
        "metal3": "met3",
        "via3": "via3",
        "metal4": "met4",
    }
    gds_data = {
        **result,
        "shapes": [
            {**item, "layer": layer_names[item["layer"]]}
            for item in result["shapes"]
        ],
        "labels": [
            {**item, "layer": layer_names[item["layer"]], "gds_label": item["net"]}
            for item in result["labels"]
        ],
    }
    gds_report = direct_gds(
        gds_data, root / result["source_checkpoint"]["gds"], args.gds
    )
    args.gds_report.parent.mkdir(parents=True, exist_ok=True)
    args.gds_report.write_text(
        json.dumps(gds_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"geometry": result["counts"], "gds": gds_report},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
