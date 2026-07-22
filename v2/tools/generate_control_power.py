#!/usr/bin/env python3
"""Generate the frozen V2 control-power geometry and a routes-only Magic cell.

The overlay contains no foundry standard-cell polygons.  Magic may therefore
write this small routing cell normally; the release assembler later references
it from the byte-preserved control-placement GDS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from check_route_feasibility import component_ports


TOP = "v2_control_power_overlay"
DBU = 0.005
VIA1_HALF = 0.13
VIA2_HALF = 0.20
VIA3_HALF = 0.20
M2_HALF = 0.20


def snap(value: float) -> float:
    return round(round(value / DBU) * DBU, 6)


def ordered_bbox(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [snap(min(x0, x1)), snap(min(y0, y1)),
            snap(max(x0, x1)), snap(max(y0, y1))]


class Geometry:
    def __init__(self) -> None:
        self.shapes: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []
        self._count = 0

    def rect(
        self, net: str, layer: str, bbox: list[float], kind: str, owner: str
    ) -> None:
        box = ordered_bbox(*map(float, bbox))
        if box[2] - box[0] < DBU - 1e-9 or box[3] - box[1] < DBU - 1e-9:
            raise ValueError(f"zero-area {layer} rectangle for {owner}: {box}")
        self.shapes.append({
            "id": f"PWR_{self._count:04d}",
            "net": net,
            "layer": layer,
            "bbox_um": box,
            "kind": kind,
            "owner": owner,
        })
        self._count += 1

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

    def square(
        self, net: str, layer: str, x: float, y: float, half: float,
        kind: str, owner: str,
    ) -> None:
        self.rect(net, layer, [x - half, y - half, x + half, y + half], kind, owner)

    def m1_to_m3(self, net: str, x: float, y: float, owner: str) -> None:
        self.square(net, "via1", x, y, VIA1_HALF, "via", owner)
        self.square(net, "metal2", x, y, M2_HALF, "via_landing", owner)
        self.square(net, "via2", x, y, VIA2_HALF, "via", owner)

    def m3_to_m4(self, net: str, x: float, y: float, owner: str) -> None:
        self.square(net, "via3", x, y, VIA3_HALF, "via", owner)

    def li_to_m3(self, net: str, x: float, y: float, owner: str) -> None:
        self.square(net, "locali", x, y, 0.085, "terminal_landing", owner)
        self.square(net, "viali", x, y, 0.085, "via", owner)
        self.rect(net, "metal1", [x - 0.145, y - 0.115,
                                   x + 0.145, y + 0.115],
                  "terminal_landing", owner)
        self.m1_to_m3(net, x, y, owner)
        self.rect(net, "metal3", [x - 0.31, y - 0.20,
                                   x + 0.31, y + 0.20],
                  "terminal_landing", owner)

    def label(self, net: str, layer: str, point: list[float], owner: str) -> None:
        self.labels.append({"net": net, "layer": layer,
                            "point_um": [snap(float(point[0])), snap(float(point[1]))],
                            "owner": owner})


def placed_component(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record["name"], "pcell": record["pcell"],
        "x": record["center"][0], "y": record["center"][1],
        "orientation": record["orientation"],
    }


def generate(
    plan: dict[str, Any], placement: dict[str, Any], integration: dict[str, Any],
    dimensions: dict[str, Any], catalog: dict[str, Any], source_path: Path,
) -> dict[str, Any]:
    expected_hash = plan["source_checkpoint"]["sha256"]
    actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"control-placement GDS hash changed: {actual_hash} != {expected_hash}"
        )

    rules = plan["rules"]
    row_height = float(rules["row_height"])
    m1_width = float(rules["m1_rail_width"])
    m3_width = float(rules["m3_strap_width"])
    m4_width = float(rules["m4_trunk_width"])
    geometry = Geometry()

    # Full-height TinyTapeout supply entries are deliberately explicit.  The
    # outer VDPWR source crosses beneath the inner VGND source only on M3.
    for source in plan["source_rails"]:
        geometry.rect(source["net"], source["layer"], source["bbox"],
                      "source_rail", f"{source['net']}_source")
        geometry.label(source["net"], source["layer"], source["label_point"],
                       f"{source['net']}_source")

    top = plan["top_distribution"]
    bx0, bx1, by = map(float, top["VDPWR"]["m3_source_bridge"])
    geometry.wire_h("VDPWR", "metal3", bx0, bx1, by, m3_width,
                    "required_crossing_bridge", "VDPWR_top_source_bridge")
    geometry.m3_to_m4("VDPWR", bx0, by, "VDPWR_top_source")
    geometry.m3_to_m4("VDPWR", bx1, by, "VDPWR_top_trunk_entry")
    x0, x1, y = map(float, top["VDPWR"]["m4_trunk"])
    geometry.wire_h("VDPWR", "metal4", x0, x1, y, m4_width,
                    "distribution_trunk", "VDPWR_top_trunk")
    x0, x1, y = map(float, top["VGND"]["m4_trunk"])
    geometry.wire_h("VGND", "metal4", x0, x1, y, m4_width,
                    "distribution_trunk", "VGND_top_trunk")

    trim = plan["trim_distribution"]
    sx, sy0, sy1 = map(float, trim["VDPWR"]["spine"])
    geometry.wire_v("VDPWR", "metal3", sx, sy0, sy1, m3_width,
                    "distribution_spine", "VDPWR_trim_spine")
    geometry.m3_to_m4("VDPWR", sx, sy0, "VDPWR_trim_spine_bottom")
    geometry.m3_to_m4("VDPWR", sx, sy1, "VDPWR_trim_spine_top")
    x0, x1, y = map(float, trim["VDPWR"]["m4_trunk"])
    geometry.wire_h("VDPWR", "metal4", x0, x1, y, m4_width,
                    "distribution_trunk", "VDPWR_trim_trunk")
    sx, sy0, sy1 = map(float, trim["VGND"]["spine"])
    geometry.wire_v("VGND", "metal4", sx, sy0, sy1, m4_width,
                    "distribution_spine", "VGND_trim_spine")
    x0, x1, y = map(float, trim["VGND"]["m4_trunk"])
    geometry.wire_h("VGND", "metal4", x0, x1, y, m4_width,
                    "distribution_trunk", "VGND_trim_trunk")

    rail_records: list[dict[str, Any]] = []
    contact_records: list[dict[str, Any]] = []
    for region_name, region in placement["regions"].items():
        x0, y0, x1, _ = map(float, region["bbox"])
        rows = int(region["row_count"])
        strap_spec = plan["region_straps"][region_name]
        rail_y: dict[str, list[float]] = {"VDPWR": [], "VGND": []}
        for boundary in range(rows + 1):
            net = "VGND" if boundary % 2 == 0 else "VDPWR"
            y = y0 + boundary * row_height
            owner = f"{region_name}_rail_{boundary:02d}"
            geometry.wire_h(net, "metal1", x0, x1, y, m1_width,
                            "standard_cell_row_rail", owner)
            rail_y[net].append(y)
            rail_records.append({
                "region": region_name, "boundary": boundary, "net": net,
                "y_um": snap(y), "x_span_um": [snap(x0), snap(x1)],
            })
            for strap_x in map(float, strap_spec[net]):
                contact_owner = f"{owner}_strap_{snap(strap_x)}"
                geometry.m1_to_m3(net, strap_x, y, contact_owner)
                contact_records.append({
                    "region": region_name, "boundary": boundary, "net": net,
                    "point_um": [snap(strap_x), snap(y)],
                })

        for net in ("VDPWR", "VGND"):
            trunk_y = float(strap_spec["trunk_y"][net])
            y_low = min(min(rail_y[net]), trunk_y)
            y_high = max(max(rail_y[net]), trunk_y)
            for index, strap_x in enumerate(map(float, strap_spec[net])):
                owner = f"{region_name}_{net}_strap_{index}"
                geometry.wire_v(net, "metal3", strap_x, y_low, y_high,
                                m3_width, "region_strap", owner)
                geometry.m3_to_m4(net, strap_x, trunk_y,
                                  f"{owner}_trunk_contact")

    # The channel-local trim inverters and phase-selector logic predate the
    # synthesized control core.  They are fixed standard cells, but do not sit
    # in any generated placement region.  Give their alternating row edges the
    # same explicit, redundant M1-to-M3 power treatment rather than assuming
    # that abutting standard-cell rails are connected by the source GDS.
    helper_rail_records: list[dict[str, Any]] = []
    helper_contact_records: list[dict[str, Any]] = []
    helper_power = plan["fixed_helper_standard_cell_power"]
    for group in helper_power["groups"]:
        for segment in group["segments"]:
            rail_x0, rail_x1 = map(float, segment["rail_x_span"])
            for rail_index, rail in enumerate(group["rails"]):
                net = rail["net"]
                y = float(rail["y"])
                owner = (
                    f"{group['name']}_{segment['name']}_rail_{rail_index:02d}"
                )
                geometry.wire_h(net, "metal1", rail_x0, rail_x1, y, m1_width,
                                "fixed_helper_row_rail", owner)
                helper_rail_records.append({
                    "group": group["name"], "segment": segment["name"],
                    "rail": rail_index, "net": net, "y_um": snap(y),
                    "x_span_um": [snap(rail_x0), snap(rail_x1)],
                })
                for contact_x in map(float, segment["contact_x_by_net"][net]):
                    contact_owner = f"{owner}_strap_{snap(contact_x)}"
                    geometry.m1_to_m3(net, contact_x, y, contact_owner)
                    helper_contact_records.append({
                        "group": group["name"], "segment": segment["name"],
                        "rail": rail_index, "net": net,
                        "point_um": [snap(contact_x), snap(y)],
                    })

    helper_nwell_records: list[dict[str, Any]] = []
    for bridge in helper_power["nwell_bridges"]:
        geometry.rect("VDPWR", "nwell", bridge["bbox"],
                      "fixed_helper_nwell_bridge", bridge["name"])
        helper_nwell_records.append({
            "name": bridge["name"],
            "bbox_um": ordered_bbox(*map(float, bridge["bbox"])),
        })

    helper_distribution_records: list[dict[str, Any]] = []
    helper_via3_records: list[dict[str, Any]] = []
    for wire_index, wire in enumerate(helper_power["distribution_wires"]):
        net = wire["net"]
        layer = wire["layer"]
        orientation = wire["orientation"]
        a = float(wire["a"])
        b = float(wire["b"])
        fixed = float(wire["fixed"])
        width = float(wire["width"])
        owner = wire["owner"]
        if orientation == "h":
            geometry.wire_h(net, layer, a, b, fixed, width,
                            "fixed_helper_distribution", owner)
            bbox = ordered_bbox(a, fixed - width / 2, b, fixed + width / 2)
        elif orientation == "v":
            geometry.wire_v(net, layer, fixed, a, b, width,
                            "fixed_helper_distribution", owner)
            bbox = ordered_bbox(fixed - width / 2, a, fixed + width / 2, b)
        else:
            raise ValueError(f"{owner}: unsupported helper-power orientation {orientation}")
        helper_distribution_records.append({
            "index": wire_index, "net": net, "layer": layer,
            "orientation": orientation, "bbox_um": bbox, "owner": owner,
        })
        for via_index, point in enumerate(wire.get("via3_at", [])):
            x, y = map(float, point)
            via_owner = f"{owner}_via3_{via_index}"
            geometry.m3_to_m4(net, x, y, via_owner)
            helper_via3_records.append({
                "net": net, "point_um": [snap(x), snap(y)],
                "owner": via_owner,
            })

    components = {
        item["name"]: placed_component(item)
        for item in integration["analog_support_components"]
    }
    endpoint_records: list[dict[str, Any]] = []
    for endpoint in plan["analog_vdpwr_endpoints"]:
        expected = list(map(float, endpoint["expected_point"]))
        component_name = str(endpoint["component"])
        if component_name in components:
            points = component_ports(
                components[component_name], endpoint["terminal"],
                dimensions, catalog,
            )
            if len(points) != 1:
                raise ValueError(
                    f"{component_name}.{endpoint['terminal']} has {len(points)} ports"
                )
            x, y = map(float, points[0])
        elif component_name in ("LOAD_N", "LOAD_P"):
            # The matched output loads are part of the analog placement rather
            # than analog_support_components.  Their R1 points are frozen from
            # the measured PCell port catalog and checked again by extraction.
            x, y = expected
        else:
            raise ValueError(f"unknown analog VDPWR component {component_name}")
        if abs(x - expected[0]) > 1e-6 or abs(y - expected[1]) > 1e-6:
            raise ValueError(
                f"{endpoint['component']}.{endpoint['terminal']} moved: {[x, y]} != {expected}"
            )
        owner = f"{endpoint['component']}_{endpoint['terminal']}_VDPWR"
        connection = endpoint.get("connection", "source_rail")
        if connection == "source_rail":
            bridge_x = float(endpoint["source_bridge_end_x"])
            geometry.wire_h("VDPWR", "metal3", 2.0, bridge_x, y, m3_width,
                            "required_crossing_bridge", f"{owner}_source_bridge")
            geometry.m3_to_m4("VDPWR", 2.0, y, f"{owner}_source_contact")
            geometry.m3_to_m4("VDPWR", bridge_x, y, f"{owner}_route_entry")
            geometry.wire_h("VDPWR", "metal4", bridge_x, x, y, m4_width,
                            "analog_supply_route", owner)
            geometry.m3_to_m4("VDPWR", x, y, f"{owner}_terminal_via3")
            geometry.li_to_m3("VDPWR", x, y, f"{owner}_terminal_stack")
        elif connection == "phase_selector_vdpwr_trunk":
            trunk_y = float(endpoint["trunk_y"])
            geometry.li_to_m3("VDPWR", x, y, f"{owner}_terminal_stack")
            geometry.wire_v("VDPWR", "metal3", x, y, trunk_y, m3_width,
                            "matched_load_supply_drop", owner)
            geometry.m3_to_m4("VDPWR", x, trunk_y, f"{owner}_trunk_via3")
        else:
            raise ValueError(f"{owner}: unsupported connection {connection}")
        endpoint_records.append({
            "net": "VDPWR", "component": endpoint["component"],
            "terminal": endpoint["terminal"], "point_um": [snap(x), snap(y)],
            "connection": connection,
        })

    return {
        "schema_version": 1,
        "units": "um",
        "status": "generated control power candidate",
        "source_checkpoint": plan["source_checkpoint"],
        "output_top": plan["output_top"],
        "overlay_top": TOP,
        "policy": plan["policy"],
        "rules": rules,
        "shapes": geometry.shapes,
        "labels": geometry.labels,
        "row_rails": rail_records,
        "upper_contacts": contact_records,
        "fixed_helper_rails": helper_rail_records,
        "fixed_helper_contacts": helper_contact_records,
        "fixed_helper_distribution": helper_distribution_records,
        "fixed_helper_via3": helper_via3_records,
        "fixed_helper_nwell_bridges": helper_nwell_records,
        "analog_endpoints": endpoint_records,
        "counts": {
            "shapes": len(geometry.shapes),
            "labels": len(geometry.labels),
            "row_rails": len(rail_records),
            "upper_contacts": len(contact_records),
            "fixed_helper_rails": len(helper_rail_records),
            "fixed_helper_contacts": len(helper_contact_records),
            "fixed_helper_distribution": len(helper_distribution_records),
            "fixed_helper_via3": len(helper_via3_records),
            "fixed_helper_nwell_bridges": len(helper_nwell_records),
            "via1": sum(item["layer"] == "via1" for item in geometry.shapes),
            "via2": sum(item["layer"] == "via2" for item in geometry.shapes),
            "via3": sum(item["layer"] == "via3" for item in geometry.shapes),
        },
    }


def magic_tcl(geometry: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in geometry["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((
            f"# {item['id']} {item['net']} {item['kind']} {item['owner']}",
            f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}",
        ))
    for item in geometry["labels"]:
        x, y = item["point_um"]
        commands.extend((
            f"# label {item['net']} {item['owner']}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{{item['net']}}} FreeSans 0.10u -met4",
        ))
    body = "\n".join(commands)
    text = f"""# Generated by v2/tools/generate_control_power.py; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_power overlay magic]
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
puts "CONTROL_POWER_OVERLAY_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR control_power_overlay_drc.txt]
    error "refusing power overlay with $drc_count DRC errors"
}}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {TOP}.mag
feedback clear
gds compress 0
gds write {TOP}.gds
set gds_feedback [feedback count]
puts "CONTROL_POWER_OVERLAY_GDS_FEEDBACK_COUNT=$gds_feedback"
if {{$gds_feedback != 0}} {{
    feedback save control_power_overlay_gds_feedback.txt
    error "refusing power overlay with $gds_feedback GDS writer problems"
}}
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_power_plan.json"))
    parser.add_argument("--placement", type=Path,
                        default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--integration", type=Path,
                        default=Path("v2/layout/integration_plan.json"))
    parser.add_argument("--dimensions", type=Path,
                        default=Path("v2/layout/pcell_dimensions.json"))
    parser.add_argument("--catalog", type=Path,
                        default=Path("v2/layout/port_catalog.json"))
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--tcl", type=Path,
                        default=Path("build/v2/control_power/overlay.tcl"))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = generate(
        plan,
        json.loads(args.placement.read_text(encoding="utf-8")),
        json.loads(args.integration.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
        Path(plan["source_checkpoint"]["gds"]),
    )
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(geometry, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    magic_tcl(geometry, args.tcl)
    print(json.dumps(geometry["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
