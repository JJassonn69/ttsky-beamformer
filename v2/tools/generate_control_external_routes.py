#!/usr/bin/env python3
"""Route the nine remaining external digital inputs into the frozen V2 core."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_phase_routes import Geometry, snap
from generate_control_service_routes import (
    _candidate_accesses,
    _is_clear,
    _source_index,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET1,
    MET2,
    MET3,
    MET4,
    flatten_orthogonal_rectangles,
    flatten_rectangles,
    parse_gds,
)


def _wire_box(
    horizontal: bool,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float,
) -> list[float]:
    half = width / 2.0
    if horizontal:
        return [snap(min(x0, x1)), snap(y0 - half),
                snap(max(x0, x1)), snap(y0 + half)]
    return [snap(x0 - half), snap(min(y0, y1)),
            snap(x0 + half), snap(max(y0, y1))]


def _track_candidates(rules: dict[str, Any]) -> list[float]:
    top = float(rules["highest_track_y"])
    bottom = float(rules["lowest_track_y"])
    pitch = float(rules["track_pitch"])
    count = int(round((top - bottom) / pitch))
    tracks = [snap(top - index * pitch) for index in range(count + 1)]
    if tracks[-1] < bottom - 1e-9:
        tracks.pop()
    return tracks


def _candidate_boxes(
    net: str,
    access_layer: str,
    access_x: float,
    access_y: float,
    leaf_x: float,
    leaf_y: float,
    pin_x: float,
    pin_y: float,
    drop_x: float,
    track_y: float,
    topology: str,
    bend_order: str,
    rules: dict[str, Any],
) -> tuple[list[tuple[str, list[float], str]], dict[str, int]]:
    m1 = float(rules["metal1_pad_half_width"])
    v1 = float(rules["via1_half_width"])
    m2 = float(rules["metal2_landing_half_width"])
    v2 = float(rules["via2_half_width"])
    m3x = float(rules["metal3_landing_half_x"])
    m3y = float(rules["metal3_landing_half_y"])
    v3 = float(rules["via3_half_width"])
    m4 = float(rules["metal4_landing_half_width"])
    pin_m4_x = float(rules["metal4_pin_half_width_x"])
    boxes: list[tuple[str, list[float], str]] = []

    if access_layer == "li1":
        li = float(rules["locali_half_width"])
        boxes.extend([
            ("locali", [access_x-li, access_y-li, access_x+li, access_y+li], "pin_li"),
            ("viali", [access_x-li, access_y-li, access_x+li, access_y+li], "pin_viali"),
        ])
    boxes.extend([
        ("metal1", [access_x-m1, access_y-m1, access_x+m1, access_y+m1], "pin_m1"),
        ("via1", [access_x-v1, access_y-v1, access_x+v1, access_y+v1], "pin_via1"),
        ("metal2", [access_x-m2, access_y-m2, access_x+m2, access_y+m2], "pin_m2"),
    ])
    if abs(leaf_x-access_x) > 1e-9 or abs(leaf_y-access_y) > 1e-9:
        if bend_order == "horizontal_then_vertical":
            if abs(leaf_x-access_x) > 1e-9:
                boxes.append((
                    "metal2", _wire_box(
                        True, access_x, access_y, leaf_x, access_y,
                        float(rules["metal2_width"]),
                    ), "short_m2_sidestep_h",
                ))
            if abs(leaf_y-access_y) > 1e-9:
                boxes.append((
                    "metal2", _wire_box(
                        False, leaf_x, access_y, leaf_x, leaf_y,
                        float(rules["metal2_width"]),
                    ), "short_m2_sidestep_v",
                ))
        elif bend_order == "vertical_then_horizontal":
            if abs(leaf_y-access_y) > 1e-9:
                boxes.append((
                    "metal2", _wire_box(
                        False, access_x, access_y, access_x, leaf_y,
                        float(rules["metal2_width"]),
                    ), "short_m2_sidestep_v",
                ))
            if abs(leaf_x-access_x) > 1e-9:
                boxes.append((
                    "metal2", _wire_box(
                        True, access_x, leaf_y, leaf_x, leaf_y,
                        float(rules["metal2_width"]),
                    ), "short_m2_sidestep_h",
                ))
        else:
            raise ValueError(f"unsupported M2 bend order {bend_order}")
    boxes.extend([
        ("metal2", [leaf_x-m2, leaf_y-m2, leaf_x+m2, leaf_y+m2], "leaf_m2"),
        ("via2", [leaf_x-v2, leaf_y-v2, leaf_x+v2, leaf_y+v2], "leaf_via2"),
        ("metal3", [leaf_x-m3x, leaf_y-m3y,
                    leaf_x+m3x, leaf_y+m3y], "leaf_m3_landing"),
        ("metal3", _wire_box(False, leaf_x, leaf_y, leaf_x, track_y,
                             float(rules["metal3_width"])), "leaf_m3_drop"),
    ])
    if topology == "direct_m3_drop":
        boxes.extend([
            ("via3", [drop_x-v3, pin_y-v3, drop_x+v3, pin_y+v3], "top_via3"),
            ("metal4", _wire_box(True, pin_x, pin_y, drop_x, pin_y,
                                 float(rules["metal4_width"])), "top_m4_escape"),
            ("metal4", [pin_x-pin_m4_x, pin_y-m4,
                        pin_x+pin_m4_x, pin_y+m4], "top_pin_m4"),
        ])
        return boxes, {
            "viali": int(access_layer == "li1"), "via1": 1,
            "via2": 1, "via3": 1,
        }

    boxes.extend([
        ("via3", [leaf_x-v3, track_y-v3, leaf_x+v3, track_y+v3], "leaf_via3"),
        ("metal4", [leaf_x-m4, track_y-m4, leaf_x+m4, track_y+m4], "leaf_m4"),
        ("metal4", _wire_box(True, leaf_x, track_y, drop_x, track_y,
                             float(rules["metal4_width"])), "top_m4_branch"),
        ("metal4", [drop_x-m4, track_y-m4, drop_x+m4, track_y+m4], "drop_m4"),
        ("via3", [drop_x-v3, track_y-v3, drop_x+v3, track_y+v3], "drop_via3"),
        ("metal3", [drop_x-m3x, track_y-m3y,
                    drop_x+m3x, track_y+m3y], "drop_m3_landing"),
        ("metal3", _wire_box(False, drop_x, track_y, drop_x, pin_y,
                             float(rules["metal3_width"])), "top_m3_drop"),
        ("via3", [drop_x-v3, pin_y-v3, drop_x+v3, pin_y+v3], "top_via3"),
        ("metal4", _wire_box(True, pin_x, pin_y, drop_x, pin_y,
                             float(rules["metal4_width"])), "top_m4_escape"),
        ("metal4", [pin_x-pin_m4_x, pin_y-m4,
                    pin_x+pin_m4_x, pin_y+m4], "top_pin_m4"),
    ])
    return boxes, {
        "viali": int(access_layer == "li1"), "via1": 1,
        "via2": 1, "via3": 3,
    }


def _legal_boxes(
    boxes: list[tuple[str, list[float], str]],
    net: str,
    source: dict[str, Any],
    planned: list[dict[str, Any]],
    spacing: dict[str, float],
    access_layer: str,
    met1_port_rects: list[list[float]],
) -> bool:
    for layer, box, kind in boxes:
        if layer not in spacing:
            continue
        exemptions = (
            met1_port_rects
            if layer == "metal1" and kind == "pin_m1" and access_layer == "met1"
            else None
        )
        if not _is_clear(
            layer, box, net, source, planned, spacing,
            source_exemptions=exemptions,
        ):
            return False
    return True


def _route_choice(
    net: str,
    record: dict[str, Any],
    catalog_record: dict[str, Any],
    plan: dict[str, Any],
    source: dict[str, Any],
    planned: list[dict[str, Any]],
) -> dict[str, Any]:
    mapped = [item for item in record["endpoints"]
              if item["kind"] == "standard_cell_pin"]
    external = [item for item in record["endpoints"]
                if item["kind"] == "external_top_pin"]
    if len(mapped) != 1 or len(external) != 1 or mapped[0]["direction"] != "input":
        raise ValueError(f"{net}: expected one mapped input and one external top pin")
    endpoint = mapped[0]
    pin_x, pin_y = map(float, external[0]["point_um"])
    rules = plan["rules"]
    spacing = {
        layer: float(rules[f"minimum_{layer}_clearance"])
        for layer in ("metal1", "metal2", "metal3", "metal4")
    }
    max_m2 = float(rules["maximum_m2_leaf_escape"])
    leaf_pitch = float(rules["leaf_search_pitch"])
    leaf_steps = int(rules["leaf_search_steps"])
    leaf_y_steps = int(rules["leaf_search_y_steps"])
    drop_steps = int(rules["external_drop_search_steps"])
    access_limit = int(rules["maximum_legal_access_candidates"])
    tracks = _track_candidates(rules)
    choices: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    accesses = _candidate_accesses(catalog_record)[:access_limit]
    met1_port_rects = [
        list(map(float, item["rect_um"]))
        for item in catalog_record["legal_access_rects"] if item["layer"] == "met1"
    ]
    x_offsets = range(-leaf_steps, leaf_steps + 1)
    y_offsets = range(-leaf_y_steps, leaf_y_steps + 1)
    offsets = sorted(
        ((ix, iy) for ix in x_offsets for iy in y_offsets
         if abs(ix) + abs(iy) <= leaf_steps),
        key=lambda value: (abs(value[0])+abs(value[1]),
                           abs(value[1]), abs(value[0]), value[1], value[0]),
    )
    drop_offsets = sorted(range(-drop_steps, drop_steps + 1),
                          key=lambda value: (abs(value), value))

    direct_choices: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    for access_rank, (access_layer, access_x, access_y) in enumerate(accesses):
        for drop_offset in drop_offsets:
            drop_x = snap(pin_x + drop_offset * leaf_pitch)
            for iy in y_offsets:
                leaf_y = snap(access_y + iy * leaf_pitch)
                direct_distance = abs(drop_x-access_x) + abs(leaf_y-access_y)
                if direct_distance > max_m2 + 1e-9:
                    continue
                for bend_rank, bend_order in enumerate(
                    ("horizontal_then_vertical", "vertical_then_horizontal")
                ):
                    boxes, vias = _candidate_boxes(
                        net, access_layer, access_x, access_y, drop_x, leaf_y,
                        pin_x, pin_y, drop_x, pin_y, "direct_m3_drop",
                        bend_order, rules,
                    )
                    if _legal_boxes(
                        boxes, net, source, planned, spacing,
                        access_layer, met1_port_rects,
                    ):
                        top_escape = abs(drop_x-pin_x)
                        cost = (direct_distance + abs(pin_y-leaf_y) + top_escape,
                                direct_distance, top_escape, access_rank,
                                bend_rank, abs(iy), abs(drop_offset))
                        direct_choices.append((cost, {
                            "topology": "direct_m3_drop", "track_y_um": snap(pin_y),
                            "access_layer": access_layer,
                            "access_um": [snap(access_x), snap(access_y)],
                            "leaf_um": [snap(drop_x), snap(leaf_y)],
                            "leaf_x_um": snap(drop_x),
                            "external_drop_x_um": snap(drop_x),
                            "external_pin_um": [snap(pin_x), snap(pin_y)],
                            "m1_escape_manhattan_um": 0.0,
                            "m2_leaf_escape_um": snap(direct_distance),
                            "m3_length_um": snap(abs(pin_y-leaf_y)),
                            "m4_length_um": snap(top_escape),
                            "via_counts": vias, "boxes": boxes,
                            "m2_bend_order": bend_order, "endpoint": endpoint,
                        }))
    if direct_choices:
        return min(direct_choices, key=lambda item: item[0])[1]

    for access_rank, (access_layer, access_x, access_y) in enumerate(accesses):
        for ix, iy in offsets:
            leaf_x = snap(access_x + ix * leaf_pitch)
            leaf_y = snap(access_y + iy * leaf_pitch)
            m2_distance = abs(leaf_x-access_x) + abs(leaf_y-access_y)
            if m2_distance > max_m2 + 1e-9:
                continue
            minimum_m3_length = abs(pin_y-leaf_y)
            for drop_offset in drop_offsets:
                drop_x = snap(pin_x + drop_offset * leaf_pitch)
                m4_length = abs(drop_x-leaf_x) + abs(drop_x-pin_x)
                minimum_total_length = m2_distance + minimum_m3_length + m4_length
                if choices and minimum_total_length > choices[0][0][1] + 1e-9:
                    continue
                for bend_rank, bend_order in enumerate(
                    ("horizontal_then_vertical", "vertical_then_horizontal")
                ):
                    for track_rank, track_y in enumerate(tracks):
                        m3_length = abs(track_y-leaf_y) + abs(pin_y-track_y)
                        total_length = m2_distance + m3_length + m4_length
                        if choices and total_length > choices[0][0][1] + 1e-9:
                            continue
                        boxes, vias = _candidate_boxes(
                            net, access_layer, access_x, access_y, leaf_x, leaf_y,
                            pin_x, pin_y, drop_x, track_y, "m3_m4_m3_branch",
                            bend_order, rules,
                        )
                        if not _legal_boxes(
                            boxes, net, source, planned, spacing,
                            access_layer, met1_port_rects,
                        ):
                            continue
                        cost = (1.0, total_length, m4_length, m3_length,
                                track_rank, access_rank, bend_rank,
                                abs(ix)+abs(iy), abs(drop_offset), abs(iy), abs(ix))
                        candidate = {
                            "topology": "m3_m4_m3_branch", "track_y_um": snap(track_y),
                            "access_layer": access_layer,
                            "access_um": [snap(access_x), snap(access_y)],
                            "leaf_um": [snap(leaf_x), snap(leaf_y)],
                            "leaf_x_um": snap(leaf_x),
                            "external_drop_x_um": snap(drop_x),
                            "external_pin_um": [snap(pin_x), snap(pin_y)],
                            "m1_escape_manhattan_um": 0.0,
                            "m2_leaf_escape_um": snap(m2_distance),
                            "m3_length_um": snap(m3_length),
                            "m4_length_um": snap(m4_length), "via_counts": vias,
                            "boxes": boxes, "m2_bend_order": bend_order,
                            "endpoint": endpoint,
                        }
                        choices.append((cost, candidate))
                        choices.sort(key=lambda item: item[0])
                        choices = choices[:1]
                        break
    if not choices:
        raise ValueError(f"{net}: no obstacle-clean external route")
    return min(choices, key=lambda item: item[0])[1]


def generate(
    plan: dict[str, Any],
    allocation: dict[str, Any],
    catalog: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    for key, field in (
        ("source_checkpoint", "gds"),
        ("allocation_checkpoint", "json"),
        ("pin_access_checkpoint", "json"),
    ):
        path = root / plan[key][field]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != plan[key]["sha256"]:
            raise ValueError(f"{key} changed: {actual}")
    records = {
        item["net"]: item for item in allocation["nets"]
        if item["class"] == "external_input"
    }
    order = list(plan["routing_order"])
    if set(records) != set(order) or len(order) != len(set(order)):
        raise ValueError("external routing order differs from allocation")
    catalog_by_key = {(item["instance"], item["pin"]): item
                      for item in catalog["records"]}

    structures, database_um = parse_gds(root / plan["source_checkpoint"]["gds"])
    source_rectangles = flatten_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um
    )
    source_rectangles[MET1] = flatten_orthogonal_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um, {MET1}
    )[MET1]
    source = _source_index(source_rectangles)
    geometry = Geometry()
    routes: list[dict[str, Any]] = []

    for net in order:
        record = records[net]
        endpoint = next(item for item in record["endpoints"]
                        if item["kind"] == "standard_cell_pin")
        key = (endpoint["instance"], endpoint["pin"])
        access = catalog_by_key.get(key)
        if access is None or access["net"] != net:
            raise ValueError(f"{net}: missing exact pin-access catalog record")
        choice = _route_choice(net, record, access, plan, source, geometry.shapes)
        for layer, box, kind in choice.pop("boxes"):
            geometry.rect(net, layer, box, kind)
        geometry.labels.append({
            "net": net, "layer": "metal4", "point_um": choice["external_pin_um"]
        })
        routes.append({
            "net": net,
            "mapped_instance": endpoint["instance"],
            "mapped_cell": endpoint["cell"],
            "mapped_pin": endpoint["pin"],
            "mapped_direction": endpoint["direction"],
            "catalog_legal": True,
            "direction_reversals": 0,
            **{key: value for key, value in choice.items() if key != "endpoint"},
        })

    counts = Counter(item["layer"] for item in geometry.shapes)
    return {
        "schema_version": 1,
        "units": "um",
        "status": "generated external-control boundary overlay",
        "source_checkpoint": plan["source_checkpoint"],
        "allocation_checkpoint": plan["allocation_checkpoint"],
        "pin_access_checkpoint": plan["pin_access_checkpoint"],
        "top": plan["overlay_top"],
        "routes": sorted(routes, key=lambda item: item["net"]),
        "shapes": geometry.shapes,
        "labels": sorted(geometry.labels, key=lambda item: item["net"]),
        "counts": {
            "routes": len(routes), "shapes": len(geometry.shapes),
            "labels": len(geometry.labels), "by_layer": dict(sorted(counts.items())),
            "direct_routes": sum(item["topology"] == "direct_m3_drop" for item in routes),
            "branched_routes": sum(item["topology"] == "m3_m4_m3_branch" for item in routes),
        },
    }


def magic_tcl(data: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in data["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((
            f"# {item['id']} {item['net']} {item['kind']}",
            f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}",
        ))
    for item in data["labels"]:
        x, y = item["point_um"]
        commands.extend((
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{{item['net']}}} FreeSans 0.10u -met4",
        ))
    body = "\n".join(commands)
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing external_overlay]
file mkdir $OUT_DIR
load {data['top']} -silent
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
puts "CONTROL_EXTERNAL_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "external overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {data['top']}.mag
feedback clear
gds compress 0
gds write {data['top']}.gds
set feedback_count [feedback count]
puts "CONTROL_EXTERNAL_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{
    feedback save external_overlay_gds_feedback.txt
    error "external overlay GDS writer feedback"
}}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path,
                        default=Path("v2/layout/control_external_route_plan.json"))
    parser.add_argument("--allocation", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--catalog", type=Path,
                        default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--geometry", type=Path,
                        default=Path("build/v2/control_routing/external_geometry.json"))
    parser.add_argument("--tcl", type=Path,
                        default=Path("build/v2/control_routing/generate_external_overlay.tcl"))
    args = parser.parse_args()
    data = generate(
        json.loads(args.plan.read_text()),
        json.loads(args.allocation.read_text()),
        json.loads(args.catalog.read_text()),
        Path(__file__).resolve().parents[2],
    )
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    magic_tcl(data, args.tcl)
    print(json.dumps(data["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
