#!/usr/bin/env python3
"""Convert audited OpenROAD DEF routes into an exact routes-only GDS overlay.

Magic remains useful for inspecting the generated geometry, but it must not be
the release writer for OpenROAD cut rectangles.  Magic interprets a painted
``via`` rectangle as a request to synthesize contacts and can reject a legal
single-cut LEF via as having no room for contacts.  The direct writer below
emits the audited DEF wire and via rectangles byte-for-byte at 1 nm GDS DBU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from check_control_openroad_routes import (
    LAYER_ORDER,
    PATCH_RECT_RE,
    ROUTE_RE,
    SECOND_POINT_RE,
    VIA_LAYERS,
    net_blocks,
)
from assemble_control_placement_gds import (
    BGNSTR,
    ENDSTR,
    ENDEL,
    INT4,
    NODATA,
    STRNAME,
    XY,
    ascii_record,
    make_record,
    record_type,
    records,
    split_library,
    structure_name,
)


DBU = 1000.0
GRID = 0.005
MAGIC_LAYERS = {
    "li1": "locali",
    "mcon": "viali",
    "met1": "metal1",
    "via": "via1",
    "met2": "metal2",
    "via2": "via2",
    "met3": "metal3",
    "via3": "via3",
    "met4": "metal4",
}
GDS_LAYERS = {
    "li1": (67, 20),
    "mcon": (67, 44),
    "met1": (68, 20),
    "via": (68, 44),
    "met2": (69, 20),
    "via2": (69, 44),
    "met3": (70, 20),
    "via3": (70, 44),
    "met4": (71, 20),
}

BOUNDARY = 0x08
TEXT = 0x0C
LAYER = 0x0D
DATATYPE = 0x0E
TEXTTYPE = 0x16
STRING = 0x19
INT2 = 0x02
ASCII = 0x06


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snap(value: float) -> float:
    # Snap through integer database units.  Direct float division can move an
    # already legal 5 nm coordinate by one grid step at values such as
    # 186.145 um because of binary rounding at the half-way comparison.
    database_units = int(round(float(value) * DBU))
    grid_units = int(round(GRID * DBU))
    return round(round(database_units / grid_units) * grid_units / DBU, 6)


def rectangle(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [snap(min(x0, x1)), snap(min(y0, y1)),
            snap(max(x0, x1)), snap(max(y0, y1))]


def via_family(name: str) -> str:
    family = next((prefix for prefix in VIA_LAYERS if name.startswith(prefix)), None)
    if family is None:
        raise ValueError(f"unsupported routed via {name}")
    return family


def route_geometry(
    block: str,
    net: str,
    offset: list[float],
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    offset_x, offset_y = map(float, offset)
    shapes: list[dict[str, Any]] = []
    label: dict[str, Any] | None = None
    segment_count = 0
    via_count = 0
    patch_count = 0
    route_layers: set[str] = set()
    for line in block.splitlines():
        match = ROUTE_RE.match(line)
        if not match:
            continue
        layer, x_text, y_text, first_extension_text, tail = match.groups()
        x = int(x_text) / DBU + offset_x
        y = int(y_text) / DBU + offset_y
        route_layers.add(layer)
        second = SECOND_POINT_RE.match(tail)
        if second:
            x2_text, y2_text, second_extension_text = second.groups()
            x2 = x if x2_text == "*" else int(x2_text) / DBU + offset_x
            y2 = y if y2_text == "*" else int(y2_text) / DBU + offset_y
            width = float(plan["wire_widths"][layer])
            half = width / 2.0
            first_extension = (
                half if first_extension_text is None
                else int(first_extension_text) / DBU
            )
            second_extension = (
                half if second_extension_text is None
                else int(second_extension_text) / DBU
            )
            if abs(x - x2) < 1e-12:
                if y2 >= y:
                    box = rectangle(
                        x - half, y - first_extension,
                        x + half, y2 + second_extension,
                    )
                else:
                    box = rectangle(
                        x - half, y2 - second_extension,
                        x + half, y + first_extension,
                    )
            elif abs(y - y2) < 1e-12:
                if x2 >= x:
                    box = rectangle(
                        x - first_extension, y - half,
                        x2 + second_extension, y + half,
                    )
                else:
                    box = rectangle(
                        x2 - second_extension, y - half,
                        x + first_extension, y + half,
                    )
            else:
                raise ValueError(f"{net}: non-Manhattan route segment")
            shapes.append({
                "net": net,
                "layer": layer,
                "bbox_um": box,
                "kind": "openroad_wire",
            })
            if label is None:
                label = {
                    "net": net,
                    "layer": layer,
                    "point_um": [snap((x + x2) / 2.0), snap((y + y2) / 2.0)],
                }
            segment_count += 1
            continue
        patch = PATCH_RECT_RE.match(tail)
        if patch:
            dx0, dy0, dx1, dy1 = (int(value) / DBU for value in patch.groups())
            shapes.append({
                "net": net,
                "layer": layer,
                "bbox_um": rectangle(x + dx0, y + dy0, x + dx1, y + dy1),
                "kind": "openroad_patch",
            })
            patch_count += 1
            continue
        via_name = tail.strip().split()[0] if tail.strip() else ""
        family = via_family(via_name)
        geometry = plan["via_geometries"].get(family)
        if geometry is None:
            raise ValueError(f"{net}: via family {family} is absent from the frozen plan")
        for via_layer, relative in geometry:
            dx0, dy0, dx1, dy1 = map(float, relative)
            shapes.append({
                "net": net,
                "layer": via_layer,
                "bbox_um": rectangle(x + dx0, y + dy0, x + dx1, y + dy1),
                "kind": f"openroad_via_{family}",
            })
        via_count += 1
    if label is None:
        raise ValueError(f"{net}: routed DEF has no wire segment")
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in shapes:
        key = (item["layer"], *item["bbox_um"])
        unique[key] = item
    return list(unique.values()), {
        "net": net,
        "segment_count": segment_count,
        "via_count": via_count,
        "patch_count": patch_count,
        "layers": sorted(route_layers, key=LAYER_ORDER.__getitem__),
        "label": label,
    }


def generate(plan: dict[str, Any], root: Path) -> dict[str, Any]:
    source = root / plan["source_checkpoint"]["gds"]
    if sha256(source) != plan["source_checkpoint"]["sha256"]:
        raise ValueError("powered placement GDS differs from the frozen route source")
    route_checkpoint = plan["route_checkpoint"]
    for field, hash_field in (
        ("jobs", "jobs_sha256"),
        ("audit", "audit_sha256"),
        ("routed_def", "routed_def_sha256"),
        ("wire_length", "wire_length_sha256"),
        ("placement", "placement_sha256"),
        ("mapping", "mapping_sha256"),
    ):
        path = root / route_checkpoint[field]
        if sha256(path) != route_checkpoint[hash_field]:
            raise ValueError(f"{field} differs from the frozen route checkpoint")
    jobs = json.loads((root / route_checkpoint["jobs"]).read_text(encoding="utf-8"))
    audit = json.loads((root / route_checkpoint["audit"]).read_text(encoding="utf-8"))
    if audit.get("status") != "pass" or audit.get("errors"):
        raise ValueError("refusing to emit an unaudited OpenROAD route")
    if audit.get("maximum_route_layer") != plan["maximum_route_layer"]:
        raise ValueError("routed maximum layer differs from the frozen plan")

    output_root = root / "build/v2/control_routing/openroad"
    audited_artifacts = audit.get("artifact_sha256", {})
    for job in jobs["jobs"]:
        region = job["region"]
        expected = audited_artifacts.get(region, {}).get("routed_def")
        route_path = output_root / region / "routed.def"
        if expected is None or sha256(route_path) != expected:
            raise ValueError(
                f"{region} routed DEF differs from the audited route checkpoint"
            )

    shapes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    route_index = 0
    for job in jobs["jobs"]:
        blocks = net_blocks(
            (output_root / job["region"] / "routed.def").read_text(encoding="utf-8")
        )
        for net_id, original in sorted(job["net_ids"].items()):
            net_shapes, route = route_geometry(
                blocks[net_id], original, job["coordinate_offset_um"], plan
            )
            matching_top_pins = [
                item for item in job.get("top_pins", {}).values()
                if item["net"] == original
            ]
            if len(matching_top_pins) > 1:
                raise ValueError(f"{original}: multiple router-owned top pins")
            for pin in matching_top_pins:
                px, py = map(float, pin["point_um"])
                rx0, ry0, rx1, ry1 = map(float, pin["rect_um"])
                ox, oy = map(float, job["coordinate_offset_um"])
                net_shapes.append({
                    "net": original,
                    "layer": pin["layer"],
                    "bbox_um": rectangle(
                        ox + px + rx0, oy + py + ry0,
                        ox + px + rx1, oy + py + ry1,
                    ),
                    "kind": "openroad_top_pin",
                })
            route["net_id"] = net_id
            route["region"] = job["region"]
            # GDS strings can contain '/', but Magic rejects those labels on
            # import.  Use a stable, unique physical label and retain the
            # reversible physical-to-logical mapping in the frozen geometry.
            route["gds_label"] = f"R{route_index:03d}"
            route["shape_count"] = len(net_shapes)
            label = route.pop("label")
            label["gds_label"] = route["gds_label"]
            labels.append(label)
            shapes.extend(net_shapes)
            routes.append(route)
            route_index += 1
    if len(routes) != int(plan["expected_route_count"]):
        raise ValueError(f"emitted {len(routes)} routes, expected {plan['expected_route_count']}")
    counts = Counter(item["layer"] for item in shapes)
    return {
        "schema_version": 2,
        "units": "um",
        "status": "generated from audited OpenROAD detailed routes",
        "source_checkpoint": plan["source_checkpoint"],
        "route_checkpoint": plan["route_checkpoint"],
        "top": plan["overlay_top"],
        "routes": sorted(routes, key=lambda item: item["net"]),
        "shapes": shapes,
        "labels": sorted(labels, key=lambda item: item["net"]),
        "label_net_map": {
            item["gds_label"]: item["net"]
            for item in sorted(routes, key=lambda item: item["gds_label"])
        },
        "counts": {
            "routes": len(routes),
            "labels": len(labels),
            "shapes": len(shapes),
            "segments": sum(item["segment_count"] for item in routes),
            "vias": sum(item["via_count"] for item in routes),
            "patches": sum(item["patch_count"] for item in routes),
            "by_layer": dict(sorted(counts.items(), key=lambda item: LAYER_ORDER.get(item[0], 99))),
        },
    }


def magic_tcl(data: dict[str, Any], output: Path) -> None:
    """Write an inspection-only Magic script; direct GDS is authoritative."""
    commands: list[str] = []
    for index, item in enumerate(data["shapes"]):
        x0, y0, x1, y1 = item["bbox_um"]
        commands.extend((
            f"# RTE_{index:05d} {item['net']} {item['kind']}",
            f"paint_rect {MAGIC_LAYERS[item['layer']]} {x0:.6f} {y0:.6f} {x1:.6f} {y1:.6f}",
        ))
    for item in data["labels"]:
        x, y = item["point_um"]
        commands.extend((
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{{item['gds_label']}}} FreeSans 0.10u -{MAGIC_LAYERS[item['layer']]}",
        ))
    body = "\n".join(commands)
    text = f"""# Generated from audited OpenROAD routed DEF; do not edit.
set PROJECT_ROOT [pwd]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing openroad_overlay magic]
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
set drc_count [drc list count total]
puts "CONTROL_OPENROAD_OVERLAY_DRC_COUNT=$drc_count"
if {{$drc_count != 0}} {{
    feedback save [file join $OUT_DIR control_openroad_overlay_drc.txt]
    error "refusing OpenROAD overlay with $drc_count DRC errors"
}}
property FIXED_BBOX 0 0 334.88 225.76
cd $OUT_DIR
save {data['top']}.mag
feedback clear
gds compress 0
gds write {data['top']}.gds
set gds_feedback [feedback count]
puts "CONTROL_OPENROAD_OVERLAY_PREVIEW_GDS_FEEDBACK_COUNT=$gds_feedback"
quit -noprompt
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def int2_record(kind: int, value: int) -> bytes:
    return make_record(kind, INT2, struct.pack(">h", value))


def boundary_element(layer: int, datatype: int, bbox_um: list[float]) -> list[bytes]:
    x0, y0, x1, y1 = (round(float(value) * DBU) for value in bbox_um)
    if x0 >= x1 or y0 >= y1:
        raise ValueError(f"invalid GDS boundary {bbox_um}")
    points = (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)
    return [
        make_record(BOUNDARY, NODATA),
        int2_record(LAYER, layer),
        int2_record(DATATYPE, datatype),
        make_record(XY, INT4, struct.pack(">10i", *points)),
        make_record(ENDEL, NODATA),
    ]


def text_element(layer: int, name: str, point_um: list[float]) -> list[bytes]:
    x, y = (round(float(value) * DBU) for value in point_um)
    return [
        make_record(TEXT, NODATA),
        int2_record(LAYER, layer),
        int2_record(TEXTTYPE, 5),
        make_record(XY, INT4, struct.pack(">ii", x, y)),
        make_record(STRING, ASCII, name.encode("ascii")),
        make_record(ENDEL, NODATA),
    ]


def direct_gds(
    data: dict[str, Any], source_path: Path, output_path: Path
) -> dict[str, Any]:
    """Emit exact route rectangles while inheriting the source GDS units."""

    source_stream = records(source_path.read_bytes())
    header, source_structures, endlib = split_library(source_stream)
    source_names = {structure_name(item) for item in source_structures}
    if data["top"] in source_names:
        raise ValueError(f"overlay top {data['top']} collides with source GDS")
    bgnstr = next(
        record for record in source_structures[0] if record_type(record) == BGNSTR
    )
    structure: list[bytes] = [bgnstr, ascii_record(STRNAME, data["top"])]
    for item in data["shapes"]:
        layer, datatype = GDS_LAYERS[item["layer"]]
        structure.extend(boundary_element(layer, datatype, item["bbox_um"]))
    for item in data["labels"]:
        layer, _datatype = GDS_LAYERS[item["layer"]]
        structure.extend(text_element(layer, item["gds_label"], item["point_um"]))
    structure.append(make_record(ENDSTR, NODATA))
    output = b"".join(header + structure) + endlib
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    return {
        "status": "pass",
        "writer": "direct deterministic GDS boundary writer",
        "source_gds": str(source_path),
        "source_sha256": sha256(source_path),
        "output_gds": str(output_path),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "top": data["top"],
        "dbu_per_um": int(DBU),
        "boundary_count": len(data["shapes"]),
        "label_count": len(data["labels"]),
        "bytes": len(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("v2/layout/control_openroad_route_plan.json"))
    parser.add_argument("--geometry", type=Path, default=Path("build/v2/control_routing/openroad_route_geometry.json"))
    parser.add_argument("--tcl", type=Path, default=Path("build/v2/control_routing/generate_openroad_overlay.tcl"))
    parser.add_argument(
        "--gds", type=Path,
        default=Path("build/v2/control_routing/openroad_overlay/direct/v2_control_openroad_routes.gds"),
    )
    parser.add_argument(
        "--gds-report", type=Path,
        default=Path("build/v2/control_routing/openroad_overlay/direct/gds_write_audit.json"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    data = generate(json.loads(args.plan.read_text(encoding="utf-8")), root)
    args.geometry.parent.mkdir(parents=True, exist_ok=True)
    args.geometry.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    magic_tcl(data, args.tcl)
    report = direct_gds(data, root / data["source_checkpoint"]["gds"], args.gds)
    args.gds_report.parent.mkdir(parents=True, exist_ok=True)
    args.gds_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"geometry": data["counts"], "gds": report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
