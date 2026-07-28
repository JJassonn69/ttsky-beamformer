#!/usr/bin/env python3
"""Generate the twelve short control-core-to-phase-selector handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_openroad_overlay import direct_gds


DBU = 0.005


def snap(value: float) -> float:
    return round(round(value / DBU) * DBU, 6)


def bbox(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [snap(min(x0, x1)), snap(min(y0, y1)),
            snap(max(x0, x1)), snap(max(y0, y1))]


class Geometry:
    def __init__(self) -> None:
        self.shapes: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []

    def rect(self, net: str, layer: str, box: list[float], kind: str) -> None:
        self.shapes.append({
            "id": f"PHASE_{len(self.shapes):04d}", "net": net,
            "layer": layer, "bbox_um": bbox(*map(float, box)), "kind": kind,
        })

    def wire_h(self, net: str, layer: str, x0: float, x1: float,
               y: float, width: float, kind: str) -> None:
        self.rect(net, layer, [x0, y - width / 2, x1, y + width / 2], kind)

    def wire_v(self, net: str, layer: str, x: float, y0: float,
               y1: float, width: float, kind: str) -> None:
        self.rect(net, layer, [x - width / 2, y0, x + width / 2, y1], kind)


def generate(plan: dict[str, Any], allocation: dict[str, Any], root: Path) -> dict[str, Any]:
    source = root / plan["source_checkpoint"]["gds"]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != plan["source_checkpoint"]["sha256"]:
        raise ValueError(f"phase source hash changed: {source_hash}")
    allocation_path = root / plan["allocation_checkpoint"]["json"]
    allocation_hash = hashlib.sha256(allocation_path.read_bytes()).hexdigest()
    if allocation_hash != plan["allocation_checkpoint"]["sha256"]:
        raise ValueError(f"phase allocation hash changed: {allocation_hash}")
    openroad_checkpoint = plan["openroad_handoff_checkpoint"]
    openroad_path = root / openroad_checkpoint["geometry"]
    openroad_hash = hashlib.sha256(openroad_path.read_bytes()).hexdigest()
    if openroad_hash != openroad_checkpoint["geometry_sha256"]:
        raise ValueError(f"phase OpenROAD geometry changed: {openroad_hash}")
    openroad = json.loads(openroad_path.read_text(encoding="utf-8"))
    boundary_pins = {}
    for shape in openroad["shapes"]:
        if (shape["kind"] == "openroad_top_pin"
                and shape["layer"] == "met2"
                and shape["net"].startswith(("phase_select", "phase_enable"))):
            x0, y0, x1, y1 = map(float, shape["bbox_um"])
            boundary_pins[shape["net"]] = {
                "point_um": [snap((x0+x1)/2), snap((y0+y1)/2)],
                "bbox_um": [snap(x0), snap(y0), snap(x1), snap(y1)],
            }
    for net, boundary_pin in boundary_pins.items():
        pin_x0, pin_y0, pin_x1, pin_y1 = boundary_pin["bbox_um"]
        accesses = []
        for shape in openroad["shapes"]:
            if (shape["net"] != net or shape["kind"] != "openroad_wire"
                    or shape["layer"] != "met2"):
                continue
            x0, y0, x1, y1 = map(float, shape["bbox_um"])
            if ((y1-y0) > (x1-x0)
                    and x0 < pin_x1 and pin_x0 < x1
                    and y0 <= pin_y1 and pin_y0 <= y1):
                accesses.append(snap((x0+x1)/2))
        if len(accesses) != 1:
            raise ValueError(
                f"{net}: expected one vertical M2 access at boundary pin, found {len(accesses)}"
            )
        boundary_pin["route_access_x_um"] = accesses[0]

    rules = plan["rules"]
    interface_y = float(plan["selector_interface_y"])
    g = Geometry()
    routes: list[dict[str, Any]] = []
    records = [item for item in allocation["nets"] if item["class"] == "phase_handoff"]
    for record in sorted(records, key=lambda item: item["net"]):
        net = record["net"]
        pins = [item for item in record["endpoints"] if item["kind"] == "standard_cell_pin"]
        handoffs = [item for item in record["endpoints"] if item["kind"] == "phase_selector_handoff"]
        if len(pins) != 1 or len(handoffs) != 1 or pins[0]["direction"] != "output":
            raise ValueError(f"{net}: expected one output driver and one phase handoff")
        driver, handoff = pins[0], handoffs[0]
        hx, hy = map(float, handoff["point_um"])
        if net not in boundary_pins:
            raise ValueError(f"{net}: missing router-owned M2 boundary pin")
        boundary_pin = boundary_pins[net]
        boundary_x, boundary_y = boundary_pin["point_um"]
        if abs(boundary_x-hx) > 1e-9 or abs(boundary_y-hy) > 1e-9:
            raise ValueError(f"{net}: router boundary pin moved away from analog handoff")
        if interface_y >= boundary_y:
            raise ValueError(f"{net}: selector interface must be below boundary pin")

        column_x = float(boundary_pin["route_access_x_um"])
        pin_x0, _pin_y0, pin_x1, _pin_y1 = boundary_pin["bbox_um"]
        if not (pin_x0-1e-9 <= column_x <= pin_x1+1e-9):
            raise ValueError(f"{net}: analog column does not land inside M2 boundary pin")
        g.wire_v(net, "metal2", column_x, interface_y, boundary_y,
                 float(rules["metal2_width"]), "analog_root_column")
        if abs(column_x-boundary_x) > DBU/2:
            # Fill the complete landing height.  A centreline-width jog leaves
            # a narrow same-net notch between an offset M2 column and the via
            # landing; the foundry KLayout deck correctly treats that notch as
            # a spacing violation.
            g.wire_h(net, "metal2", column_x, boundary_x, interface_y,
                     2.0 * float(rules["metal2_landing_half_y"]),
                     "interface_jog")
        m2x = float(rules["metal2_landing_half_x"])
        m2y = float(rules["metal2_landing_half_y"])
        v2 = float(rules["via2_half_width"])
        m3v2 = float(rules["metal3_via2_landing_half_width"])
        g.rect(net, "metal2", [boundary_x-m2x, interface_y-m2y,
                                boundary_x+m2x, interface_y+m2y],
               "interface_via2_m2")
        g.rect(net, "via2", [boundary_x-v2, interface_y-v2,
                              boundary_x+v2, interface_y+v2],
               "interface_via2")
        g.rect(net, "metal3", [boundary_x-m3v2, interface_y-m3v2,
                                boundary_x+m3v2, interface_y+m3v2],
               "interface_via2_m3")

        if handoff["layer"] == "metal4":
            m3x = float(rules["metal3_via3_landing_half_x"])
            m3y = float(rules["metal3_via3_landing_half_y"])
            v3 = float(rules["via3_half_width"])
            m4 = float(rules["metal4_landing_half_width"])
            # Via2 and via3 share one M3 landing at this stacked transition.
            # Emitting a second identical rectangle is redundant GDS and made
            # visual review needlessly ambiguous.
            if m3x > m3v2 or m3y > m3v2:
                raise ValueError(
                    f"{net}: shared M3 via-stack landing is undersized"
                )
            g.rect(net, "via3", [boundary_x-v3, interface_y-v3,
                                  boundary_x+v3, interface_y+v3],
                   "interface_via3")
            g.rect(net, "metal4", [boundary_x-m4, interface_y-m4,
                                    boundary_x+m4, interface_y+m4],
                   "interface_m4")
        elif handoff["layer"] != "metal3":
            raise ValueError(f"{net}: unsupported handoff layer {handoff['layer']}")

        g.labels.append({"net": net, "layer": handoff["layer"],
                         "point_um": [boundary_x, snap(interface_y)]})
        routes.append({
            "net": net,
            "signal": net.split("[", 1)[0],
            "driver_instance": driver["instance"],
            "driver_pin": driver["pin"],
            "router_boundary_um": [boundary_x, boundary_y],
            "router_boundary_bbox_um": boundary_pin["bbox_um"],
            "metal2_column_x_um": column_x,
            "handoff_um": [snap(hx), snap(hy)],
            "selector_interface_um": [boundary_x, snap(interface_y)],
            "handoff_layer": handoff["layer"],
            "m2_length_um": snap(boundary_y-interface_y + abs(column_x-boundary_x)),
            "via_counts": {"viali": 0, "via1": 0, "via2": 1,
                           "via3": int(handoff["layer"] == "metal4")},
            "direction_reversals": 0,
        })

    layers = Counter(item["layer"] for item in g.shapes)
    return {
        "schema_version": 1, "units": "um",
        "status": "generated analog-only phase-handoff overlay",
        "source_checkpoint": plan["source_checkpoint"],
        "allocation_checkpoint": plan["allocation_checkpoint"],
        "openroad_handoff_checkpoint": plan["openroad_handoff_checkpoint"],
        "top": plan["overlay_top"], "routes": routes,
        "shapes": g.shapes, "labels": g.labels,
        "counts": {"routes": len(routes), "shapes": len(g.shapes),
                   "labels": len(g.labels), "by_layer": dict(sorted(layers.items()))},
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
        magic_layer = item["layer"].replace("metal", "met")
        commands.extend((
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{{item['net']}}} FreeSans 0.10u -{magic_layer}",
        ))
    body = "\n".join(commands)
    top = geometry["top"]
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing phase_overlay magic]
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
puts "CONTROL_PHASE_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "phase overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {top}.mag
feedback clear
gds compress 0
gds write {top}.gds
set feedback_count [feedback count]
puts "CONTROL_PHASE_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{
    feedback save [file join $OUT_DIR phase_overlay_gds_feedback.txt]
    error "phase overlay GDS writer feedback"
}}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_phase_route_plan.json"))
    parser.add_argument("--allocation", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_routing/phase_geometry.json"))
    parser.add_argument("--tcl", type=Path,
                        default=Path("build/v2/control_routing/generate_phase_overlay.tcl"))
    parser.add_argument(
        "--gds", type=Path,
        default=Path(
            "build/v2/control_routing/phase_overlay/direct/"
            "v2_control_phase_routes_overlay.gds"
        ),
    )
    parser.add_argument(
        "--gds-report", type=Path,
        default=Path("build/v2/control_routing/phase_overlay/direct/gds_write_audit.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = generate(json.loads(args.plan.read_text()), json.loads(args.allocation.read_text()), root)
    args.geometry.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    magic_tcl(result, args.tcl)
    layer_names = {
        "locali": "li1", "viali": "mcon", "metal1": "met1",
        "via1": "via", "metal2": "met2", "via2": "via2",
        "metal3": "met3", "via3": "via3", "metal4": "met4",
    }
    gds_data = {
        **result,
        "shapes": [
            {**item, "layer": layer_names[item["layer"]]}
            for item in result["shapes"]
        ],
        "labels": [
            {
                **item,
                "layer": layer_names[item["layer"]],
                "gds_label": item["net"],
            }
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
