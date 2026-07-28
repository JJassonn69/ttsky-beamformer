#!/usr/bin/env python3
"""Route every local and regional V2 standard-cell signal deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_phase_routes import Geometry, snap
from generate_control_service_routes import (
    _candidate_accesses,
    _is_clear,
    _source_index,
    _wire_box,
    choose_pin_escape,
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


def _tracks(window: dict[str, Any], pitch: float) -> list[float]:
    low = float(window["lowest_track_y_um"])
    high = float(window["highest_track_y_um"])
    count = int(round((high - low) / pitch))
    result = [snap(low + index * pitch) for index in range(count + 1)]
    return [value for value in result if value <= high + 1e-9]


def _conductor_shapes(
    boxes: list[tuple[str, list[float], str]], net: str
) -> list[dict[str, Any]]:
    return [
        {"net": net, "layer": layer, "bbox_um": list(map(float, box))}
        for layer, box, _kind in boxes
        if layer in {"metal1", "metal2", "metal3", "metal4"}
    ]


def _choose_route(
    net: str,
    record: dict[str, Any],
    catalogs: dict[tuple[str, str], dict[str, Any]],
    plan: dict[str, Any],
    source: dict[str, Any],
    planned: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoints = [
        item for item in record["endpoints"]
        if item["kind"] == "standard_cell_pin"
    ]
    if len(endpoints) < 2:
        raise ValueError(f"{net}: internal net has fewer than two mapped endpoints")
    region = record["regions"]
    if len(region) != 1:
        raise ValueError(f"{net}: internal route crosses regions {region}")
    region_name = region[0]
    rules = plan["rules"]
    spacing = {
        layer: float(rules[f"minimum_{layer}_clearance"])
        for layer in ("metal1", "metal2", "metal3", "metal4")
    }
    median_y = statistics.median(
        float(item["point_um"][1]) for item in endpoints
    )
    tracks = sorted(
        _tracks(plan["routing_windows"][region_name], float(rules["track_pitch_um"])),
        key=lambda value: (abs(value - median_y), value),
    )
    limit = int(rules.get("maximum_track_candidates_per_net", 0))
    if limit > 0:
        tracks = tracks[:limit]
    endpoints = sorted(
        endpoints,
        key=lambda item: (
            len(_candidate_accesses(catalogs[(item["instance"], item["pin"])])),
            float(item["point_um"][0]),
            item["instance"],
            item["pin"],
        ),
    )
    failures: Counter[str] = Counter()

    for track_y in tracks:
        temporary = list(planned)
        choices: list[tuple[dict[str, Any], dict[str, Any]]] = []
        failed = False
        for endpoint in endpoints:
            key = (endpoint["instance"], endpoint["pin"])
            catalog = catalogs.get(key)
            if catalog is None or catalog["net"] != net:
                raise ValueError(f"{net}: missing exact catalog record for {key}")
            try:
                pin_diagnostics: Counter[str] = Counter()
                choice = choose_pin_escape(
                    net, endpoint, catalog, track_y, plan, source, temporary,
                    diagnostics=pin_diagnostics,
                )
            except ValueError:
                failures[f"pin:{endpoint['instance']}|{endpoint['pin']}"] += 1
                for reason, count in pin_diagnostics.items():
                    failures[f"detail:{reason}"] += count
                failed = True
                break
            temporary.extend(_conductor_shapes(choice["boxes"], net))
            choices.append((endpoint, choice))
        if failed:
            continue

        leaf_xs = [float(choice["leaf_x_um"]) for _endpoint, choice in choices]
        trunk_box = _wire_box(
            True,
            min(leaf_xs),
            track_y,
            max(leaf_xs),
            track_y,
            float(rules["metal4_width"]),
        )
        if not _is_clear(
            "metal4", trunk_box, net, source, temporary, spacing
        ):
            failures["trunk_metal4"] += 1
            continue
        maximum_vertical = max(
            abs(track_y - float(choice["pin_um"][1]))
            for _endpoint, choice in choices
        )
        if maximum_vertical > (
            float(rules["maximum_vertical_overhead_per_endpoint_um"]) + 1e-9
        ):
            failures["vertical_overhead"] += 1
            continue
        return {
            "region": region_name,
            "track_y_um": snap(track_y),
            "trunk_bbox_um": [snap(value) for value in trunk_box],
            "trunk_x_span_um": [snap(min(leaf_xs)), snap(max(leaf_xs))],
            "trunk_length_um": snap(max(leaf_xs) - min(leaf_xs)),
            "maximum_vertical_overhead_um": snap(maximum_vertical),
            "endpoint_choices": choices,
        }
    raise ValueError(
        f"{net}: no obstacle-clean internal track and pin-access tree; "
        f"failures={failures.most_common()}"
    )


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

    routed_classes = set(plan["routed_classes"])
    catalogs = {
        (item["instance"], item["pin"]): item for item in catalog["records"]
    }
    records = [
        item for item in allocation["nets"] if item["class"] in routed_classes
    ]

    def route_priority(item: dict[str, Any]) -> tuple[int, int, float, str]:
        endpoints = [
            endpoint for endpoint in item["endpoints"]
            if endpoint["kind"] == "standard_cell_pin"
        ]
        access_margin = min(
            len(_candidate_accesses(catalogs[(endpoint["instance"], endpoint["pin"])]))
            for endpoint in endpoints
        )
        return (
            access_margin,
            -len(endpoints),
            -float(item["hpwl_um"]),
            item["net"],
        )

    records.sort(key=route_priority)
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
    rules = plan["rules"]

    for record in records:
        net = record["net"]
        selected = _choose_route(
            net, record, catalogs, plan, source, geometry.shapes
        )
        endpoint_records: list[dict[str, Any]] = []
        for endpoint, choice in selected.pop("endpoint_choices"):
            pin_x, pin_y = map(float, choice["pin_um"])
            lift_x, lift_y = map(float, choice["lift_um"])
            via2_x, via2_y = map(float, choice["via2_um"])
            leaf_x = float(choice["leaf_x_um"])
            if choice["pin_layer"] == "li1":
                li = float(rules["locali_half_width"])
                geometry.rect(net, "locali", [pin_x-li, pin_y-li, pin_x+li, pin_y+li], "pin_li")
                geometry.rect(net, "viali", [pin_x-li, pin_y-li, pin_x+li, pin_y+li], "pin_viali")
            elif choice["pin_layer"] != "met1":
                raise ValueError(f"{net}: unsupported pin layer {choice['pin_layer']}")
            for layer, box, kind in choice["boxes"]:
                geometry.rect(net, layer, box, kind)
            v1 = float(rules["via1_half_width"])
            v2 = float(rules["via2_half_width"])
            v3 = float(rules["via3_half_width"])
            geometry.rect(net, "via1", [lift_x-v1, lift_y-v1, lift_x+v1, lift_y+v1], "lift_via1")
            geometry.rect(net, "via2", [via2_x-v2, via2_y-v2, via2_x+v2, via2_y+v2], "leaf_via2")
            geometry.rect(net, "via3", [leaf_x-v3, selected["track_y_um"]-v3,
                                          leaf_x+v3, selected["track_y_um"]+v3], "trunk_via3")
            endpoint_records.append({
                "instance": endpoint["instance"],
                "cell": endpoint["cell"],
                "pin": endpoint["pin"],
                "direction": endpoint["direction"],
                "pin_layer": choice["pin_layer"],
                "pin_um": choice["pin_um"],
                "lift_um": choice["lift_um"],
                "leaf_x_um": choice["leaf_x_um"],
                "via2_um": choice["via2_um"],
                "leaf_topology": choice["leaf_topology"],
                "m1_escape_manhattan_um": choice["m1_escape_manhattan_um"],
                "m2_leaf_escape_um": choice["m2_leaf_escape_um"],
                "bend_order": choice["bend_order"],
                "catalog_legal": True,
            })
        geometry.rect(net, "metal4", selected["trunk_bbox_um"], "shortest_interval_trunk")
        label_x = snap(sum(selected["trunk_x_span_um"]) / 2.0)
        geometry.labels.append({
            "net": net, "layer": "metal4",
            "point_um": [label_x, selected["track_y_um"]],
        })
        routes.append({
            "net": net,
            "class": record["class"],
            "mapped_endpoint_count": len(endpoint_records),
            "direction_reversals": 0,
            **selected,
            "endpoints": endpoint_records,
        })

    counts = Counter(item["layer"] for item in geometry.shapes)
    return {
        "schema_version": 1,
        "units": "um",
        "status": "generated complete internal-control routing overlay",
        "source_checkpoint": plan["source_checkpoint"],
        "allocation_checkpoint": plan["allocation_checkpoint"],
        "pin_access_checkpoint": plan["pin_access_checkpoint"],
        "top": plan["overlay_top"],
        "routes": sorted(routes, key=lambda item: item["net"]),
        "shapes": geometry.shapes,
        "labels": sorted(geometry.labels, key=lambda item: item["net"]),
        "counts": {
            "routes": len(routes),
            "local_direct": sum(item["class"] == "local_direct" for item in routes),
            "regional_trunk": sum(item["class"] == "regional_trunk" for item in routes),
            "mapped_endpoints": sum(item["mapped_endpoint_count"] for item in routes),
            "shapes": len(geometry.shapes),
            "labels": len(geometry.labels),
            "by_layer": dict(sorted(counts.items())),
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
    output.write_text(f"""# Generated; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing internal_overlay]
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
puts "CONTROL_INTERNAL_OVERLAY_DRC_COUNT=$count"
if {{$count != 0}} {{ error "internal overlay has $count DRC errors" }}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {data['top']}.mag
feedback clear
gds compress 0
gds write {data['top']}.gds
set feedback_count [feedback count]
puts "CONTROL_INTERNAL_OVERLAY_GDS_FEEDBACK_COUNT=$feedback_count"
if {{$feedback_count != 0}} {{ error "internal overlay GDS writer feedback" }}
quit -noprompt
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_internal_route_plan.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--catalog", type=Path, default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/internal_geometry.json"))
    parser.add_argument("--tcl", type=Path, default=Path("build/v2/control_routing/generate_internal_overlay.tcl"))
    args = parser.parse_args()
    data = generate(
        json.loads(args.plan.read_text()),
        json.loads(args.allocation.read_text()),
        json.loads(args.catalog.read_text()),
        ROOT,
    )
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    magic_tcl(data, args.tcl)
    print(json.dumps(data["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
