#!/usr/bin/env python3
"""Generate shielded service spines and short region fanout branches."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from generate_control_phase_routes import Geometry, snap

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET1, MET2, MET3, MET4, flatten_orthogonal_rectangles,
    flatten_rectangles, parse_gds, rectangle_gap,
)
from check_control_phase_routes import distance  # noqa: E402


def allocate_row_tracks(plan: dict[str, Any], records: dict[str, Any]) -> dict[tuple[str, int, str], float]:
    """Compact row branches near their pins while enforcing a full M4 pitch."""
    result: dict[tuple[str, int, str], float] = {}
    allocator = plan["row_branch_allocator"]
    order = {net: index for index, net in enumerate(allocator["net_order"])}
    for region in ("phase_configuration_bank", "global_control_core"):
        groups: dict[tuple[int, str], list[float]] = defaultdict(list)
        for net, record in records.items():
            for endpoint in record["endpoints"]:
                if endpoint.get("kind") == "standard_cell_pin" and endpoint.get("region") == region:
                    groups[(int(endpoint["row"]) // 2, net)].append(float(endpoint["point_um"][1]))
        ranked = sorted(
            ((statistics.median(ys), row, net) for (row, net), ys in groups.items()),
            key=lambda item: (item[0], item[1], order[item[2]]),
        )
        pitch = float(allocator["track_pitch_um"])
        lower = float(allocator[region]["lower_y_um"])
        upper = float(allocator[region]["upper_y_um"])
        tracks: list[float] = []
        for desired, _row, _net in ranked:
            tracks.append(max(desired, lower if not tracks else tracks[-1] + pitch))
        if tracks and tracks[-1] > upper:
            shift = tracks[-1] - upper
            tracks = [value - shift for value in tracks]
        if tracks and tracks[0] < lower - 1e-9:
            raise ValueError(f"{region}: row branches do not fit contracted range")
        for (_desired, row, net), track in zip(ranked, tracks):
            override_key = f"{region}|{row}|{net}"
            result[(region, row, net)] = snap(
                float(plan.get("row_branch_track_overrides", {}).get(override_key, track))
            )
    return result


def branch_key(plan: dict[str, Any], net: str, endpoint: dict[str, Any],
               row_tracks: dict[tuple[str, int, str], float]) -> tuple[str, str, float]:
    region = endpoint.get("region")
    if region == "trim_configuration_bank":
        pair = int(endpoint["row"]) // 2
        trim = plan["trim_pair_tracks"]
        if net == "serial_phase_to_trim":
            offset = float(trim["serial_phase_to_trim_last_pair_offset_y_um"])
        else:
            offset = float(trim["offset_y_um"][net])
        y = float(trim["pair_origin_y_um"]) + pair*float(trim["pair_height_um"]) + offset
        return region, f"trim_pair_{pair}", y
    if region in ("phase_configuration_bank", "global_control_core"):
        row_pair = int(endpoint["row"]) // 2
        return region, f"row_pair_{row_pair}", row_tracks[(region, row_pair, net)]
    raise ValueError(f"{net}: unsupported endpoint region {region}")


def _candidate_accesses(record: dict[str, Any]) -> list[tuple[str, float, float]]:
    selected = record["selected_access"]
    candidates: list[tuple[str, float, float]] = []
    for rect in record["legal_access_rects"]:
        points = rect.get("service_candidate_points_um", ())
        # A met1 port may be a compound orthogonal polygon represented by
        # several individually narrow LEF rectangles.  A legal via pad can
        # overlap their union even when it cannot fit inside one rectangle.
        # Exact-source checking below exempts only the named port rectangles
        # and still rejects contact with every other M1 polygon.
        if rect["layer"] == "met1" and not points:
            points = rect.get("candidate_points_um", ())
        for point in points:
            item = (rect["layer"], *map(float, point))
            if item not in candidates:
                candidates.append(item)
    selected_item = (selected["layer"], *map(float, selected["point_um"]))
    rank = {item: index for index, item in enumerate(candidates)}
    return sorted(candidates, key=lambda item: (item != selected_item, rank[item]))


def _is_clear(layer: str, box: list[float], net: str, source: dict,
              planned: list[dict[str, Any]], spacing: dict[str, float],
              check_source: bool = True,
              source_exemptions: list[list[float]] | None = None) -> bool:
    clearance = spacing[layer]
    if check_source and layer in ("metal1", "metal2", "metal3", "metal4"):
        exemptions = source_exemptions or []
        def exempt(obstacle: tuple[float, float, float, float]) -> bool:
            return any(
                all(abs(value-other) <= 1e-6 for value, other in zip(obstacle, item))
                for item in exemptions
            )
        if any(
            not exempt(obstacle)
            and rectangle_gap(tuple(box), obstacle) < clearance - 1e-9
            for obstacle in _nearby_source(source, layer, box, clearance)
        ):
            return False
    x0, y0, x1, y1 = box
    for shape in planned:
        if shape["layer"] != layer or shape["net"] == net:
            continue
        sx0, sy0, sx1, sy1 = shape["bbox_um"]
        if (sx0 >= x1+clearance or x0 >= sx1+clearance
                or sy0 >= y1+clearance or y0 >= sy1+clearance):
            continue
        if distance(box, shape["bbox_um"]) < clearance - 1e-9:
            return False
    return True


def _source_index(source: dict, bucket_um: float = 5.0) -> dict[str, Any]:
    """Index flattened source rectangles so exact-obstacle search stays fast."""
    result: dict[str, Any] = {"bucket_um": bucket_um}
    for name, gds_layer in (
        ("metal1", MET1), ("metal2", MET2), ("metal3", MET3), ("metal4", MET4)
    ):
        buckets: dict[tuple[int, int], set[tuple[float, float, float, float]]] = defaultdict(set)
        for rectangle in source[gds_layer]:
            x0, y0, x1, y1 = rectangle
            for ix in range(int(x0//bucket_um), int(x1//bucket_um)+1):
                for iy in range(int(y0//bucket_um), int(y1//bucket_um)+1):
                    buckets[(ix, iy)].add(rectangle)
        result[name] = buckets
    return result


def _nearby_source(index: dict[str, Any], layer: str, box: list[float],
                   clearance: float) -> list[tuple[float, float, float, float]]:
    bucket_um = float(index["bucket_um"])
    x0, y0, x1, y1 = box
    found: set[tuple[float, float, float, float]] = set()
    for ix in range(int((x0-clearance)//bucket_um), int((x1+clearance)//bucket_um)+1):
        for iy in range(int((y0-clearance)//bucket_um), int((y1+clearance)//bucket_um)+1):
            found.update(index[layer].get((ix, iy), ()))
    return list(found)


def _wire_box(horizontal: bool, x0: float, y0: float, x1: float, y1: float,
              width: float) -> list[float]:
    half = width / 2
    if horizontal:
        return [snap(min(x0, x1)), snap(y0-half), snap(max(x0, x1)), snap(y0+half)]
    return [snap(x0-half), snap(min(y0, y1)), snap(x0+half), snap(max(y0, y1))]


def choose_pin_escape(net: str, endpoint: dict[str, Any], catalog_record: dict[str, Any],
                      track_y: float, plan: dict[str, Any], source: dict,
                      planned: list[dict[str, Any]],
                      reservation: dict[str, Any] | None = None,
                      diagnostics: Counter[str] | None = None) -> dict[str, Any]:
    """Choose a short M1 lift and independent M2 sidestep to a clear M3 leaf."""
    rules = plan["rules"]
    spacing = {layer: float(rules[f"minimum_{layer}_clearance"])
               for layer in ("metal1", "metal2", "metal3", "metal4")}
    pitch = float(rules["pin_escape_search_pitch"])
    m1_steps = int(rules["m1_escape_search_steps"])
    leaf_steps = int(rules["m2_leaf_search_steps"])
    max_m1 = float(rules["maximum_m1_escape_manhattan"])
    max_m2 = float(rules["maximum_m2_leaf_escape"])
    lift_offsets = sorted(
        ((ix, iy) for ix in range(-m1_steps, m1_steps+1)
         for iy in range(-m1_steps, m1_steps+1) if abs(ix)+abs(iy) <= m1_steps),
        key=lambda item: (abs(item[0])+abs(item[1]), abs(item[1]), abs(item[0]), item[1], item[0]),
    )
    leaf_offsets = sorted(range(-leaf_steps, leaf_steps+1), key=lambda value: (abs(value), value))
    choices: list[tuple[tuple[float, ...], dict[str, Any]]] = []
    met1_port_rects = [
        list(map(float, item["rect_um"]))
        for item in catalog_record["legal_access_rects"]
        if item["layer"] == "met1"
    ]
    candidate_accesses = (
        [(reservation["pin_layer"], *map(float, reservation["pin_um"]))]
        if reservation is not None else _candidate_accesses(catalog_record)
    )
    candidate_accesses = candidate_accesses[:int(
        rules.get("maximum_legal_access_candidates", len(candidate_accesses))
    )]
    for access_rank, (pin_layer, px, py) in enumerate(candidate_accesses):
        for ix, iy in lift_offsets:
            lx, ly = snap(px + ix*pitch), snap(py + iy*pitch)
            m1_escape = abs(lx-px) + abs(ly-py)
            if m1_escape > max_m1 + 1e-9:
                continue
            if choices and m1_escape > choices[0][0][0] + 1e-9:
                continue
            for bend_order in ("horizontal_then_vertical", "vertical_then_horizontal"):
                m1w = float(rules["metal1_width"])
                # The painted via1 resolves to a 0.15um cut.  KLayout's
                # via.5a rule requires 0.085um M1 enclosure on two adjacent
                # edges, so every access—including an existing met1 port—gets
                # the full 0.32um M1 landing.  Named-port source rectangles
                # are exempted below, but all unrelated M1 remains an obstacle.
                m1h = float(rules["metal1_pad_half_width"])
                m2h = float(rules["metal2_landing_half_width"])
                m3x = float(rules["metal3_landing_half_x"])
                m3y = float(rules["metal3_landing_half_y"])
                m4h = float(rules["metal4_landing_half_width"])
                lift_boxes: list[tuple[str, list[float], str]] = []
                lift_boxes.append(("metal1", [px-m1h, py-m1h, px+m1h, py+m1h], "pin_m1"))
                if abs(lx-px) > 1e-9 or abs(ly-py) > 1e-9:
                    lift_boxes.append((
                        "metal1", [lx-m1h, ly-m1h, lx+m1h, ly+m1h], "lift_m1"
                    ))
                    if bend_order == "horizontal_then_vertical":
                        if abs(lx-px) > 1e-9:
                            lift_boxes.append((
                                "metal1", _wire_box(True, px, py, lx, py, m1w),
                                "pin_escape_h",
                            ))
                        if abs(ly-py) > 1e-9:
                            lift_boxes.append((
                                "metal1", _wire_box(False, lx, py, lx, ly, m1w),
                                "pin_escape_v",
                            ))
                    else:
                        if abs(ly-py) > 1e-9:
                            lift_boxes.append((
                                "metal1", _wire_box(False, px, py, px, ly, m1w),
                                "pin_escape_v",
                            ))
                        if abs(lx-px) > 1e-9:
                            lift_boxes.append((
                                "metal1", _wire_box(True, px, ly, lx, ly, m1w),
                                "pin_escape_h",
                            ))
                lift_boxes.append(("metal2", [lx-m2h, ly-m2h, lx+m2h, ly+m2h], "lift_m2"))
                blocked_lift = next((
                    f"lift:{layer}:{kind}"
                    for layer, box, kind in lift_boxes
                    if not _is_clear(
                        layer, box, net, source, planned, spacing,
                        source_exemptions=(
                            met1_port_rects
                            if pin_layer == "met1" and kind == "pin_m1" else None
                        ),
                    )
                ), None)
                if blocked_lift is not None:
                    if diagnostics is not None:
                        diagnostics[blocked_lift] += 1
                    continue
                for leaf_offset in leaf_offsets:
                    leaf_x = snap(lx + leaf_offset*pitch)
                    m2_escape = abs(leaf_x-lx)
                    if m2_escape > max_m2 + 1e-9:
                        continue
                    best_primary = min((item[0][0] for item in choices), default=float("inf"))
                    if m1_escape + m2_escape > best_primary + 1e-9:
                        continue
                    common = [
                        ("metal4", [leaf_x-m4h, track_y-m4h,
                                    leaf_x+m4h, track_y+m4h], "branch_m4_landing"),
                    ]
                    topologies = [
                        ("metal3_vertical", [
                            *([("metal2", _wire_box(True, lx, ly, leaf_x, ly,
                                                   float(rules["metal2_width"])), "m2_leaf_escape")]
                              if abs(leaf_x-lx) > 1e-9 else []),
                            ("metal2", [leaf_x-m2h, ly-m2h, leaf_x+m2h, ly+m2h], "leaf_m2"),
                            ("metal3", [leaf_x-m3x, min(ly, track_y)-m3y,
                                        leaf_x+m3x, max(ly, track_y)+m3y], "short_m3_leaf"),
                        ], [leaf_x, ly], 0),
                        ("metal2_vertical_hv", [
                            *([("metal2", _wire_box(True, lx, ly, leaf_x, ly,
                                                   float(rules["metal2_width"])), "m2_leaf_escape")]
                              if abs(leaf_x-lx) > 1e-9 else []),
                            ("metal2", _wire_box(False, leaf_x, ly, leaf_x, track_y,
                                                 float(rules["metal2_width"])), "short_m2_leaf"),
                            ("metal2", [leaf_x-m2h, track_y-m2h,
                                        leaf_x+m2h, track_y+m2h], "branch_via2_m2"),
                            ("metal3", [leaf_x-m3x, track_y-m3y,
                                        leaf_x+m3x, track_y+m3y], "branch_via2_m3"),
                        ], [leaf_x, track_y], 1),
                        ("metal2_vertical_vh", [
                            ("metal2", _wire_box(False, lx, ly, lx, track_y,
                                                 float(rules["metal2_width"])), "short_m2_leaf"),
                            *([("metal2", _wire_box(True, lx, track_y, leaf_x, track_y,
                                                   float(rules["metal2_width"])), "m2_leaf_escape")]
                              if abs(leaf_x-lx) > 1e-9 else []),
                            ("metal2", [leaf_x-m2h, track_y-m2h,
                                        leaf_x+m2h, track_y+m2h], "branch_via2_m2"),
                            ("metal3", [leaf_x-m3x, track_y-m3y,
                                        leaf_x+m3x, track_y+m3y], "branch_via2_m3"),
                        ], [leaf_x, track_y], 2),
                    ]
                    for topology, topology_boxes, via2_point, topology_rank in topologies:
                        if (
                            topology.startswith("metal2_vertical")
                            and abs(track_y - ly)
                            > float(rules.get("maximum_wrong_way_m2_vertical", float("inf")))
                            + 1e-9
                        ):
                            continue
                        leaf_boxes = topology_boxes + common
                        blocked_leaf = next((
                            f"leaf:{layer}:{kind}"
                            for layer, box, kind in leaf_boxes
                            if not _is_clear(layer, box, net, source, planned, spacing)
                        ), None)
                        if blocked_leaf is not None:
                            if diagnostics is not None:
                                diagnostics[blocked_leaf] += 1
                            continue
                        boxes = lift_boxes + leaf_boxes
                        wrong_way_penalty = (
                            0.0 if topology == "metal3_vertical"
                            else float(rules.get("wrong_way_m2_penalty_um", 0.0))
                        )
                        cost = (m1_escape + m2_escape + wrong_way_penalty,
                                m1_escape, m2_escape,
                                topology_rank, abs(track_y-ly), access_rank,
                                0 if bend_order == "horizontal_then_vertical" else 1,
                                abs(ix), abs(iy), abs(leaf_offset))
                        choices.append((cost, {
                            "pin_layer": pin_layer, "pin_um": [snap(px), snap(py)],
                            "lift_um": [lx, ly], "leaf_x_um": leaf_x,
                            "via2_um": [snap(v) for v in via2_point],
                            "leaf_topology": topology,
                            "m1_escape_manhattan_um": snap(m1_escape),
                            "m2_leaf_escape_um": snap(m2_escape),
                            "bend_order": bend_order, "boxes": boxes,
                        }))
                        # Do not return the first legal point.  A later point
                        # in the same LEF port can have a strictly shorter M1
                        # escape, and M1 movement is the highest-risk part of
                        # this route because the flattened source audit does
                        # not model non-rectangular standard-cell M1 polygons.
    if not choices:
        raise ValueError(
            f"{net}: no legal M1<={max_m1}um/M2<={max_m2}um escape for "
            f"{endpoint['instance']}|{endpoint['pin']} to track {track_y}"
        )
    return min(choices, key=lambda item: item[0])[1]


def generate(plan: dict[str, Any], allocation: dict[str, Any], catalog: dict[str, Any], root: Path) -> dict[str, Any]:
    for key, field in (("source_checkpoint", "gds"), ("allocation_checkpoint", "json"), ("pin_access_checkpoint", "json"), ("service_access_checkpoint", "json")):
        path = root / plan[key][field]
        if hashlib.sha256(path.read_bytes()).hexdigest() != plan[key]["sha256"]:
            raise ValueError(f"{key} changed")
    records = {item["net"]: item for item in allocation["nets"] if item["class"] == "service_tree"}
    if set(records) != set(plan["spines"]):
        raise ValueError("service-tree route set differs from allocation")
    catalog_by_key = {(item["instance"], item["pin"]): item for item in catalog["records"]}
    reservation_data = json.loads((root / plan["service_access_checkpoint"]["json"]).read_text())
    reservations = {
        (item["instance"], item["pin"]): item
        for item in reservation_data["reservations"]
    }
    rules = plan["rules"]
    geometry = Geometry()
    structures, database_um = parse_gds(root / plan["source_checkpoint"]["gds"])
    source_rectangles = flatten_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um
    )
    source_rectangles[MET1] = flatten_orthogonal_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um, {MET1}
    )[MET1]
    source = _source_index(source_rectangles)
    row_tracks = allocate_row_tracks(plan, records)
    routes_by_net: dict[str, dict[str, Any]] = {}
    branch_items: dict[tuple[str, str, str, float], list[dict[str, Any]]] = defaultdict(list)

    # Fixed shielded spines are placed first so every local escape treats them
    # as owned routing resources, never as after-the-fact decoration.
    y0, y1 = map(float, plan["spine_y_range"])
    for net, spine_x_raw in sorted(plan["spines"].items()):
        spine_x = float(spine_x_raw)
        geometry.wire_v(net, "metal3", spine_x, y0, y1,
                        float(rules["metal3_width"]), "service_spine")
        routes_by_net[net] = {
            "net": net, "spine_x_um": snap(spine_x),
            "spine_y_range_um": [snap(y0), snap(y1)], "mapped_pin_count": 0,
            "external_pin_count": 0, "mapped_accesses": [], "branches": [],
            "external_routes": [],
        }

    bridge_y = float(plan["ground_bridge"]["y_um"])
    source_x = float(plan["ground_bridge"]["source_m3_x_um"])
    shields = list(map(float, plan["ground_shields_x"]))
    for x in shields:
        geometry.wire_v("VGND", "metal3", x, y0, y1,
                        float(rules["metal3_width"]), "ground_shield")
    geometry.wire_h("VGND", "metal4", source_x, max(shields), bridge_y,
                    float(rules["metal4_width"]), "ground_bridge")
    # The M4 bridge already overlaps the existing M4 VGND spine at source_x;
    # no M3/via3 island is needed there.  Only the two real M3 shields descend.
    for x in shields:
        v3 = float(rules["via3_half_width"]); m4 = float(rules["metal4_landing_half_width"])
        geometry.rect("VGND", "metal3", [x-v3, bridge_y-v3, x+v3, bridge_y+v3], "ground_bridge_via3_m3")
        geometry.rect("VGND", "via3", [x-v3, bridge_y-v3, x+v3, bridge_y+v3], "ground_bridge_via3")
        geometry.rect("VGND", "metal4", [x-m4, bridge_y-m4, x+m4, bridge_y+m4], "ground_bridge_via3_m4")

    # Route all local accesses before painting shared branches.  Every lift is
    # selected against the exact completed GDS and all previously selected
    # different-net geometry.
    for net, spine_x_raw in sorted(plan["spines"].items()):
        spine_x = float(spine_x_raw)
        record = records[net]
        external = [item for item in record["endpoints"] if item["kind"] == "external_top_pin"]
        mapped = [item for item in record["endpoints"] if item["kind"] == "standard_cell_pin"]

        for endpoint in sorted(mapped, key=lambda item: (item["region"], int(item["row"]), float(item["point_um"][0]))):
            key = (endpoint["instance"], endpoint["pin"])
            access = catalog_by_key.get(key)
            if access is None or access["net"] != net or not access["selected_access"]["inside_inset_lef_port"]:
                raise ValueError(f"{net}: illegal or missing catalog access for {key}")
            reservation = reservations.get(key)
            if reservation is None or reservation["net"] != net:
                raise ValueError(f"{net}: missing frozen service access for {key}")
            region, group, track_y = branch_key(plan, net, endpoint, row_tracks)
            selected = choose_pin_escape(
                net, endpoint, access, track_y, plan, source, geometry.shapes,
                reservation,
            )
            frozen_fields = (
                "pin_layer", "pin_um", "lift_um", "leaf_x_um", "via2_um",
                "leaf_topology", "bend_order", "m1_escape_manhattan_um",
                "m2_leaf_escape_um",
            )
            if any(selected[field] != reservation[field] for field in frozen_fields):
                raise ValueError(
                    f"{net}: final route differs from frozen escape for {key}"
                )
            layer = selected["pin_layer"]
            x, y = map(float, selected["pin_um"])
            lift_x, lift_y = map(float, selected["lift_um"])
            leaf_x = float(selected["leaf_x_um"])
            via2_x, via2_y = map(float, selected["via2_um"])
            li = float(rules["locali_half_width"])
            v1 = float(rules["via1_half_width"])
            v2 = float(rules["via2_half_width"])
            v3 = float(rules["via3_half_width"])
            if layer == "li1":
                geometry.rect(net, "locali", [x-li, y-li, x+li, y+li], "pin_li")
                geometry.rect(net, "viali", [x-li, y-li, x+li, y+li], "pin_viali")
            elif layer != "met1":
                raise ValueError(f"{net}: unsupported service pin layer {layer}")
            for shape_layer, box, kind in selected["boxes"]:
                geometry.rect(net, shape_layer, box, kind)
            geometry.rect(net, "via1", [lift_x-v1, lift_y-v1, lift_x+v1, lift_y+v1], "lift_via1")
            geometry.rect(net, "via2", [via2_x-v2, via2_y-v2, via2_x+v2, via2_y+v2], "leaf_via2")
            geometry.rect(net, "via3", [leaf_x-v3, track_y-v3, leaf_x+v3, track_y+v3], "branch_via3")
            branch_items[(net, region, group, track_y)].append({"x": leaf_x, "endpoint": endpoint})
            access_record = {
                "instance": endpoint["instance"], "cell": endpoint["cell"], "pin": endpoint["pin"],
                "direction": endpoint["direction"], "pin_layer": layer, "pin_um": [snap(x), snap(y)],
                "lift_um": [snap(lift_x), snap(lift_y)],
                "leaf_x_um": snap(leaf_x),
                "m1_escape_manhattan_um": selected["m1_escape_manhattan_um"],
                "m2_leaf_escape_um": selected["m2_leaf_escape_um"],
                "leaf_topology": selected["leaf_topology"],
                "bend_order": selected["bend_order"],
                "region": region, "row": endpoint["row"], "branch_group": group,
                "branch_track_y_um": snap(track_y),
                "leaf_layer": "metal3" if selected["leaf_topology"] == "metal3_vertical" else "metal2",
                "catalog_legal": True,
            }
            routes_by_net[net]["mapped_accesses"].append(access_record)
            routes_by_net[net]["mapped_pin_count"] += 1

        # External M4 pins drop briefly through M3 to individual top tracks,
        # keeping the four long M4 routes disjoint.
        external_records: list[dict[str, Any]] = []
        for endpoint in external:
            pin_x, pin_y = map(float, endpoint["point_um"])
            track_y = float(plan["external_top_tracks_y_um"][net])
            v3 = float(rules["via3_half_width"]); m4 = float(rules["metal4_landing_half_width"])
            m3x = float(rules["metal3_landing_half_x"]); m3y = float(rules["metal3_landing_half_y"])
            for y in (pin_y, track_y):
                geometry.rect(net, "metal3", [pin_x-m3x, y-m3y, pin_x+m3x, y+m3y], "external_via3_m3")
                geometry.rect(net, "via3", [pin_x-v3, y-v3, pin_x+v3, y+v3], "external_via3")
                if abs(y-pin_y) <= 1e-9:
                    geometry.rect(net, "metal4", [pin_x-.30, y-m4, pin_x+.30, y+m4], "external_pin_m4")
                else:
                    geometry.rect(net, "metal4", [pin_x-m4, y-m4, pin_x+m4, y+m4], "external_via3_m4")
            geometry.wire_v(net, "metal3", pin_x, track_y, pin_y, float(rules["metal3_width"]), "external_drop")
            geometry.wire_h(net, "metal4", pin_x, spine_x, track_y, float(rules["metal4_width"]), "external_branch")
            geometry.rect(net, "metal3", [spine_x-v3, track_y-v3, spine_x+v3, track_y+v3], "external_spine_via3_m3")
            geometry.rect(net, "via3", [spine_x-v3, track_y-v3, spine_x+v3, track_y+v3], "external_spine_via3")
            geometry.rect(net, "metal4", [spine_x-m4, track_y-m4, spine_x+m4, track_y+m4], "external_spine_via3_m4")
            geometry.labels.append({"net": net, "layer": "metal4", "point_um": [snap(pin_x), snap(pin_y)]})
            routes_by_net[net]["external_routes"].append({"pin_um": [snap(pin_x), snap(pin_y)], "track_y_um": snap(track_y), "layer": "metal4"})
            routes_by_net[net]["external_pin_count"] += 1

        if not external:
            driver = next((item for item in routes_by_net[net]["mapped_accesses"] if item["direction"] == "output"), None)
            if driver is None:
                raise ValueError(f"{net}: service route has neither external source nor mapped driver")
            geometry.labels.append({"net": net, "layer": "metal2", "point_um": driver["lift_um"]})

    # Regional M4 branches stop before the power moat.  A short M2 bridge then
    # crosses under both orthogonal power spines and joins the assigned M3
    # service spine.  This removes the previously detected M4-to-VGND short.
    exchange_x = float(plan["power_moat_bridge"]["left_transition_x_um"])
    for (net, region, group, track_y), items in sorted(branch_items.items(), key=lambda item: item[0][3]):
        spine_x = float(plan["spines"][net])
        xs = [float(item["x"]) for item in items]
        v2 = float(rules["via2_half_width"]); v3 = float(rules["via3_half_width"])
        m2 = float(rules["metal2_landing_half_width"])
        m3x = float(rules["metal3_landing_half_x"]); m3y = float(rules["metal3_landing_half_y"])
        m4 = float(rules["metal4_landing_half_width"])
        geometry.wire_h(net, "metal4", min(xs), exchange_x, track_y,
                        float(rules["metal4_width"]), "regional_branch")
        geometry.rect(net, "metal4", [exchange_x-m4, track_y-m4, exchange_x+m4, track_y+m4], "moat_via3_m4")
        geometry.rect(net, "via3", [exchange_x-v3, track_y-v3, exchange_x+v3, track_y+v3], "moat_via3")
        geometry.rect(net, "metal3", [exchange_x-m3x, track_y-m3y, exchange_x+m3x, track_y+m3y], "moat_transition_m3")
        geometry.rect(net, "via2", [exchange_x-v2, track_y-v2, exchange_x+v2, track_y+v2], "moat_left_via2")
        geometry.rect(net, "metal2", [exchange_x-m2, track_y-m2, exchange_x+m2, track_y+m2], "moat_left_m2")
        geometry.wire_h(net, "metal2", exchange_x, spine_x, track_y,
                        float(rules["metal2_width"]), "power_moat_bridge")
        geometry.rect(net, "metal2", [spine_x-m2, track_y-m2, spine_x+m2, track_y+m2], "spine_via2_m2")
        geometry.rect(net, "via2", [spine_x-v2, track_y-v2, spine_x+v2, track_y+v2], "spine_via2")
        # The M3 landing sits on a vertical spine, so its narrow axis is X.
        # Keeping the full enclosure on Y preserves via robustness while
        # maintaining the contracted 0.30um gap to the adjacent spine.
        geometry.rect(net, "metal3", [spine_x-m3y, track_y-m3x,
                                       spine_x+m3y, track_y+m3x], "spine_via2_m3")
        routes_by_net[net]["branches"].append({
            "region": region, "group": group, "track_y_um": snap(track_y),
            "mapped_pin_count": len(items), "x_span_um": [snap(min(xs)), snap(exchange_x)],
            "power_moat_bridge_um": [snap(exchange_x), snap(spine_x)],
        })

    # GDS spacing is geometric, even when two shapes belong to the same net.
    # Close rare sub-spacing M2 re-entrant notches at an L-junction.  The
    # independent KLayout deck checks these notches even though Magic already
    # understands the shapes as one connected electrical net.
    m2_shapes = [item for item in list(geometry.shapes) if item["layer"] == "metal2"]
    for index, first in enumerate(m2_shapes):
        for second in m2_shapes[:index]:
            if first["net"] != second["net"]:
                continue
            a, b = first["bbox_um"], second["bbox_um"]
            gap = rectangle_gap(tuple(a), tuple(b))
            if gap <= 1e-9 or gap >= float(rules["minimum_metal2_clearance"]) - 1e-9:
                continue
            bridge = None
            if max(a[1], b[1]) < min(a[3], b[3]) - 1e-9:
                bridge = [min(a[2], b[2]), max(a[1], b[1]),
                          max(a[0], b[0]), min(a[3], b[3])]
            elif max(a[0], b[0]) < min(a[2], b[2]) - 1e-9:
                bridge = [max(a[0], b[0]), min(a[3], b[3]),
                          min(a[2], b[2]), max(a[1], b[1])]
            if bridge is None or not _is_clear(
                "metal2", bridge, first["net"], source, geometry.shapes,
                {"metal1": .14, "metal2": .14, "metal3": .30, "metal4": .30},
            ):
                raise ValueError(
                    f"cannot close same-net M2 notch {first['id']}/{second['id']}"
                )
            geometry.rect(first["net"], "metal2", bridge, "same_net_spacing_join")

    # Merge the rare sub-spacing M3 pairs explicitly so the flattened file has
    # neither a notch nor an ambiguous near-touch.
    m3_shapes = [item for item in list(geometry.shapes) if item["layer"] == "metal3"]
    for index, first in enumerate(m3_shapes):
        for second in m3_shapes[:index]:
            if first["net"] != second["net"]:
                continue
            a, b = first["bbox_um"], second["bbox_um"]
            gap = rectangle_gap(tuple(a), tuple(b))
            if gap <= 1e-9 or gap >= float(rules["minimum_metal3_clearance"]) - 1e-9:
                continue
            bridge = None
            if max(a[1], b[1]) < min(a[3], b[3]) - 1e-9:
                bridge = [min(a[2], b[2]), max(a[1], b[1]),
                          max(a[0], b[0]), min(a[3], b[3])]
            elif max(a[0], b[0]) < min(a[2], b[2]) - 1e-9:
                bridge = [max(a[0], b[0]), min(a[3], b[3]),
                          min(a[2], b[2]), max(a[1], b[1])]
            if bridge is None or not _is_clear("metal3", bridge, first["net"],
                                                source, geometry.shapes,
                                                {"metal1": .14, "metal2": .14,
                                                 "metal3": .30, "metal4": .30}):
                raise ValueError(f"cannot merge same-net M3 sub-spacing pair {first['id']}/{second['id']}")
            geometry.rect(first["net"], "metal3", bridge, "same_net_spacing_join")

    counts = Counter(item["layer"] for item in geometry.shapes)
    route_records = [routes_by_net[net] for net in sorted(routes_by_net)]
    return {
        "schema_version": 1, "units": "um", "status": "generated shielded service overlay",
        "source_checkpoint": plan["source_checkpoint"], "allocation_checkpoint": plan["allocation_checkpoint"],
        "pin_access_checkpoint": plan["pin_access_checkpoint"],
        "service_access_checkpoint": plan["service_access_checkpoint"],
        "top": plan["overlay_top"],
        "routes": route_records, "shapes": geometry.shapes, "labels": geometry.labels,
        "counts": {"routes": len(route_records), "shapes": len(geometry.shapes), "labels": len(geometry.labels), "by_layer": dict(sorted(counts.items()))},
    }


def magic_tcl(data: dict[str, Any], output: Path) -> None:
    commands: list[str] = []
    for item in data["shapes"]:
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((f"# {item['id']} {item['net']} {item['kind']}", f"paint_rect {item['layer']} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}"))
    for item in data["labels"]:
        x, y = item["point_um"]
        magic_layer = "met4" if item["layer"] == "metal4" else "met2"
        commands.extend((f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um", f"label {{{item['net']}}} FreeSans 0.10u -{magic_layer}"))
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing service_overlay]
file mkdir $OUT_DIR
load {data['top']} -silent
select top cell
proc paint_rect {{layer x1 y1 x2 y2}} {{ box ${{x1}}um ${{y1}}um ${{x2}}um ${{y2}}um; paint $layer }}
{chr(10).join(commands)}
select top cell
drc euclidean on
drc style drc(full)
drc check
set count [drc list count total]
puts "CONTROL_SERVICE_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "service overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {data['top']}.mag
feedback clear
gds compress 0
gds write {data['top']}.gds
set feedback_count [feedback count]
puts "CONTROL_SERVICE_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{ feedback save service_overlay_gds_feedback.txt; error "service overlay GDS writer feedback" }}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_service_route_plan.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--catalog", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/service_geometry.json"))
    parser.add_argument("--tcl", type=Path, default=Path("build/v2/control_routing/generate_service_overlay.tcl"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    data = generate(json.loads(args.plan.read_text()), json.loads(args.allocation.read_text()), json.loads(args.catalog.read_text()), root)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    magic_tcl(data, args.tcl)
    print(json.dumps(data["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
