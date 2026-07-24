#!/usr/bin/env python3
"""Independently audit OpenROAD's V2 internal-control routing results."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


DBU = 1000.0
LAYER_ORDER = {"li1": 0, "met1": 1, "met2": 2, "met3": 3, "met4": 4, "met5": 5}
VIA_LAYERS = {
    "L1M1": ("li1", "met1"),
    "M1M2": ("met1", "met2"),
    "M2M3": ("met2", "met3"),
    "M3M4": ("met3", "met4"),
    "M4M5": ("met4", "met5"),
}
ROUTE_RE = re.compile(
    r"^\s*(?:\+\s+ROUTED|NEW)\s+(\w+)\s+"
    r"\(\s*(-?\d+)\s+(-?\d+)(?:\s+(-?\d+))?\s*\)\s*(.*?)\s*;?\s*$"
)
SECOND_POINT_RE = re.compile(
    r"^\(\s*(\*|-?\d+)\s+(\*|-?\d+)(?:\s+(-?\d+))?\s*\)"
)
PATCH_RECT_RE = re.compile(
    r"^RECT\s+\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\)"
)
CONNECTION_RE = re.compile(r"\(\s+(U\d+)\s+([^ )]+)\s+\)")
TOP_PIN_CONNECTION_RE = re.compile(r"\(\s+PIN\s+([^ )]+)\s+\)")


Node = tuple[str, int, int]
Segment = tuple[str, tuple[int, int], tuple[int, int]]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def net_blocks(text: str) -> dict[str, str]:
    match = re.search(r"^NETS\s+\d+\s*;(.*?)^END NETS", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError("DEF has no NETS section")
    blocks: dict[str, str] = {}
    current: list[str] = []
    name: str | None = None
    for line in match.group(1).splitlines():
        start = re.match(r"^\s*-\s+(\S+)", line)
        if start:
            if name is not None:
                blocks[name] = "\n".join(current)
            name = start.group(1)
            current = [line]
        elif name is not None:
            current.append(line)
    if name is not None:
        blocks[name] = "\n".join(current)
    return blocks


ROUTE_WIDTH_DBU = {"li1": 170, "met1": 140, "met2": 140, "met3": 300, "met4": 300}


def parse_route(
    block: str,
) -> tuple[list[Segment], list[tuple[Node, Node]], set[str], float]:
    segments: list[Segment] = []
    vias: list[tuple[Node, Node]] = []
    layers: set[str] = set()
    extension_adjustment_um = 0.0
    for line in block.splitlines():
        match = ROUTE_RE.match(line)
        if not match:
            continue
        layer, x_text, y_text, first_extension, tail = match.groups()
        x, y = int(x_text), int(y_text)
        layers.add(layer)
        second = SECOND_POINT_RE.match(tail)
        if second:
            x2_text, y2_text, second_extension = second.groups()
            x2 = x if x2_text == "*" else int(x2_text)
            y2 = y if y2_text == "*" else int(y2_text)
            if x != x2 and y != y2:
                raise ValueError(f"non-Manhattan DEF route: {line.strip()}")
            if (x, y) != (x2, y2):
                segments.append((layer, (x, y), (x2, y2)))
                half_width = ROUTE_WIDTH_DBU[layer] / 2.0
                for extension in (first_extension, second_extension):
                    if extension is not None:
                        extension_adjustment_um += (
                            int(extension) - half_width
                        ) / DBU
            continue
        patch = PATCH_RECT_RE.match(tail)
        if patch:
            dx0, dy0, dx1, dy1 = map(int, patch.groups())
            if dx0 >= dx1 or dy0 >= dy1:
                raise ValueError(f"invalid DEF route patch rectangle: {line.strip()}")
            # A route patch expands conductor at the current graph node.  It
            # creates no additional graph edge, but OpenROAD's wire report
            # counts the amount by which its long dimension extends beyond a
            # normal width-square endpoint.  Keep that accounting independent
            # from topology while reproducing the exact rectangle in GDS.
            extension_adjustment_um += (
                max(dx1 - dx0, dy1 - dy0) - ROUTE_WIDTH_DBU[layer]
            ) / DBU
            continue
        via_name = tail.strip().split()[0] if tail.strip() else ""
        pair = next((value for prefix, value in VIA_LAYERS.items()
                     if via_name.startswith(prefix)), None)
        if pair is None:
            raise ValueError(f"unknown or absent via in route line: {line.strip()}")
        if layer not in pair:
            raise ValueError(f"via {via_name} cannot start on {layer}")
        other = pair[1] if pair[0] == layer else pair[0]
        layers.add(other)
        vias.append(((layer, x, y), (other, x, y)))
    return segments, vias, layers, extension_adjustment_um


def point_on(segment: Segment, point: tuple[int, int]) -> bool:
    _, first, second = segment
    x, y = point
    if first[0] == second[0] == x:
        return min(first[1], second[1]) <= y <= max(first[1], second[1])
    if first[1] == second[1] == y:
        return min(first[0], second[0]) <= x <= max(first[0], second[0])
    return False


def route_graph(
    segments: list[Segment], vias: list[tuple[Node, Node]]
) -> tuple[dict[Node, set[Node]], float]:
    split_points: list[set[tuple[int, int]]] = [set((first, second)) for _, first, second in segments]
    for index, first_segment in enumerate(segments):
        layer, first_a, first_b = first_segment
        for other_index in range(index + 1, len(segments)):
            other = segments[other_index]
            if other[0] != layer:
                continue
            candidates = {first_a, first_b, other[1], other[2]}
            if first_a[0] == first_b[0] and other[1][1] == other[2][1]:
                candidates.add((first_a[0], other[1][1]))
            elif first_a[1] == first_b[1] and other[1][0] == other[2][0]:
                candidates.add((other[1][0], first_a[1]))
            for point in candidates:
                if point_on(first_segment, point) and point_on(other, point):
                    split_points[index].add(point)
                    split_points[other_index].add(point)
        for via in vias:
            for node in via:
                if node[0] == layer and point_on(first_segment, (node[1], node[2])):
                    split_points[index].add((node[1], node[2]))

    edges: set[tuple[Node, Node]] = set()
    for segment, points in zip(segments, split_points):
        layer, first, second = segment
        ordered = sorted(points, key=lambda point: point[1] if first[0] == second[0] else point[0])
        for a, b in zip(ordered, ordered[1:]):
            if a == b:
                continue
            edge = ((layer, *a), (layer, *b))
            edges.add(tuple(sorted(edge)))
    edges.update(tuple(sorted(via)) for via in vias)
    graph: dict[Node, set[Node]] = defaultdict(set)
    for first, second in edges:
        graph[first].add(second)
        graph[second].add(first)
    wire_length = sum(
        (abs(first[1] - second[1]) + abs(first[2] - second[2])) / DBU
        for first, second in edges if first[0] == second[0]
    )
    return graph, wire_length


def components(graph: dict[Node, set[Node]]) -> list[set[Node]]:
    unseen = set(graph)
    result: list[set[Node]] = []
    while unseen:
        start = next(iter(unseen))
        found = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbour in graph[node] - found:
                found.add(neighbour)
                queue.append(neighbour)
        unseen -= found
        result.append(found)
    return result


def transformed_rect(
    rect: list[float], width: float, height: float, orientation: str
) -> list[float]:
    x0, y0, x1, y1 = map(float, rect)
    if orientation == "R0":
        return [x0, y0, x1, y1]
    if orientation == "MX":
        return [x0, height - y1, x1, height - y0]
    if orientation == "MY":
        return [width - x1, y0, width - x0, y1]
    if orientation == "R180":
        return [width - x1, height - y1, width - x0, height - y0]
    raise ValueError(f"unsupported placement orientation {orientation}")


def attach_pin_conductors(
    graph: dict[Node, set[Node]],
    connections: list[tuple[str, str]],
    job: dict[str, Any],
    placement_by_instance: dict[str, dict[str, Any]],
    mapped_by_instance: dict[str, dict[str, Any]],
    library: dict[str, Any],
) -> tuple[dict[Node, set[Node]], dict[str, set[Node]]]:
    """Connect route access points through the qualified LEF pin polygons.

    TritonRoute may intentionally terminate two branches at different points
    of one wide standard-cell pin.  Those branches look disconnected if only
    DEF centerlines are considered, but are electrically joined by the pin's
    foundry LEF conductor.  This function adds one synthetic node per pin and
    joins only route nodes that actually fall inside that transformed polygon.
    """

    result: dict[Node, set[Node]] = defaultdict(set)
    for node, neighbours in graph.items():
        result[node].update(neighbours)
    offset_x, offset_y = map(float, job["coordinate_offset_um"])
    membership: dict[str, set[Node]] = {}
    for component_id, pin in connections:
        instance = job["component_ids"][component_id]
        placed = placement_by_instance[instance]
        mapped = mapped_by_instance[instance]
        spec = library[mapped["short_cell"]]
        width, height = map(float, spec["size_um"])
        rectangles = []
        for access in spec["pins"][pin]["access_rects"]:
            local = transformed_rect(
                list(access["rect_um"]), width, height, placed["orientation"]
            )
            origin_x = float(placed["origin_um"][0]) - offset_x
            origin_y = float(placed["origin_um"][1]) - offset_y
            rectangles.append((
                access["layer"],
                round((origin_x + local[0]) * DBU),
                round((origin_y + local[1]) * DBU),
                round((origin_x + local[2]) * DBU),
                round((origin_y + local[3]) * DBU),
            ))
        key = f"{component_id}/{pin}"
        found = {
            node for node in graph
            if any(
                node[0] == layer
                and x0 - 1 <= node[1] <= x1 + 1
                and y0 - 1 <= node[2] <= y1 + 1
                for layer, x0, y0, x1, y1 in rectangles
            )
        }
        membership[key] = found
        pin_node = (f"PIN:{key}", 0, 0)
        result.setdefault(pin_node, set())
        for node in found:
            result[pin_node].add(node)
            result[node].add(pin_node)
    for pin in TOP_PIN_CONNECTION_RE.findall(job.get("current_net_block", "")):
        spec = job.get("top_pins", {}).get(pin)
        key = f"PIN/{pin}"
        if spec is None:
            membership[key] = set()
            result.setdefault((f"PIN:{key}", 0, 0), set())
            continue
        layer = spec["layer"]
        x, y = map(float, spec["point_um"])
        x0, y0, x1, y1 = map(float, spec["rect_um"])
        rectangle = (
            layer,
            round((x + x0) * DBU), round((y + y0) * DBU),
            round((x + x1) * DBU), round((y + y1) * DBU),
        )
        found = {
            node for node in graph
            if node[0] == rectangle[0]
            and rectangle[1] - 1 <= node[1] <= rectangle[3] + 1
            and rectangle[2] - 1 <= node[2] <= rectangle[4] + 1
        }
        membership[key] = found
        pin_node = (f"PIN:{key}", 0, 0)
        result.setdefault(pin_node, set())
        for node in found:
            result[pin_node].add(node)
            result[node].add(pin_node)
    return result, membership


def wire_report(path: Path) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0] != "drt:":
            continue
        result[fields[1]] = {
            "wire_length_um": float(fields[2]),
            "pin_count": int(fields[3]),
            "via_count": int(fields[4]),
        }
    return result


def validate(
    jobs_path: Path,
    allocation_path: Path,
    placement_path: Path,
    mapping_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    jobs_report = json.loads(jobs_path.read_text(encoding="utf-8"))
    allocation = json.loads(allocation_path.read_text(encoding="utf-8"))
    placement = json.loads(placement_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    allocation_by_net = {item["net"]: item for item in allocation["nets"]}
    placement_by_instance = {
        item["instance"]: item for item in placement["placements"]
    }
    mapped_by_instance = {item["instance"]: item for item in mapping["cells"]}
    errors: list[str] = []
    audited: list[dict[str, Any]] = []
    seen_original: set[str] = set()
    layer_counts: Counter[str] = Counter()
    total_wire = 0.0
    total_vias = 0

    if jobs_report.get("backend") != "openroad":
        errors.append("routing job manifest is not an OpenROAD manifest")
    if int(jobs_report.get("local_pair_preroute_count", -1)) != 0:
        errors.append("some internal nets bypass the production router")

    for job in jobs_report["jobs"]:
        region = job["region"]
        job_dir = output_root / region
        routed_def = job_dir / "routed.def"
        drc = job_dir / "detailed_route_drc.rpt"
        log = job_dir / "openroad.log"
        wire_csv = job_dir / "wire_length.csv"
        for path in (routed_def, drc, log, wire_csv):
            if not path.exists():
                errors.append(f"{region}: missing {path.name}")
        if any(not path.exists() for path in (routed_def, drc, log, wire_csv)):
            continue
        if drc.read_bytes():
            errors.append(f"{region}: detailed-route DRC report is not empty")
        log_text = log.read_text(encoding="utf-8")
        violations = [int(value) for value in re.findall(r"Number of violations = (\d+)", log_text)]
        routed_counts = [int(value) for value in re.findall(r"Routed nets: (\d+)", log_text)]
        if not violations or violations[-1] != 0:
            errors.append(f"{region}: final TritonRoute violation count is not zero")
        if not routed_counts or routed_counts[-1] != int(job["net_count"]):
            errors.append(f"{region}: FastRoute did not route every manifest net")
        if re.search(r"^\[ERROR|^Error:", log_text, re.MULTILINE):
            errors.append(f"{region}: OpenROAD log contains a fatal error")

        blocks = net_blocks(routed_def.read_text(encoding="utf-8"))
        reports = wire_report(wire_csv)
        expected_ids = set(job["net_ids"])
        if set(blocks) != expected_ids:
            errors.append(f"{region}: routed DEF net IDs differ from the manifest")
        if set(reports) != expected_ids:
            errors.append(f"{region}: detailed wire report net IDs differ from the manifest")

        for net_id in sorted(expected_ids):
            if net_id not in blocks or net_id not in reports:
                continue
            original = job["net_ids"][net_id]
            seen_original.add(original)
            block = blocks[net_id]
            connection_text = block.split("+ USE", 1)[0]
            connections = CONNECTION_RE.findall(connection_text)
            top_pin_connections = TOP_PIN_CONNECTION_RE.findall(connection_text)
            pin_count = len(connections) + len(top_pin_connections)
            try:
                segments, vias, layers, extension_adjustment_um = parse_route(block)
                graph, length = route_graph(segments, vias)
                job_with_block = dict(job)
                job_with_block["current_net_block"] = connection_text
                electrical_graph, pin_membership = attach_pin_conductors(
                    graph,
                    connections,
                    job_with_block,
                    placement_by_instance,
                    mapped_by_instance,
                    mapping["library"],
                )
            except ValueError as error:
                errors.append(f"{region}/{original}: {error}")
                continue
            route_groups = components(graph)
            electrical_groups = components(electrical_graph)
            leaves = [node for node, neighbours in graph.items() if len(neighbours) == 1]
            attached_nodes = set().union(*pin_membership.values()) if pin_membership else set()
            unattached_leaves = [node for node in leaves if node not in attached_nodes]
            edge_count = sum(len(value) for value in graph.values()) // 2
            cycle_rank = edge_count - len(graph) + len(route_groups)
            if len(electrical_groups) != 1:
                errors.append(
                    f"{region}/{original}: route plus LEF pins has "
                    f"{len(electrical_groups)} disconnected groups"
                )
            if cycle_rank != 0:
                errors.append(f"{region}/{original}: route graph has cycle rank {cycle_rank}")
            missing_pin_access = sorted(
                pin for pin, nodes in pin_membership.items() if not nodes
            )
            if missing_pin_access:
                errors.append(
                    f"{region}/{original}: route misses LEF pins {missing_pin_access}"
                )
            if unattached_leaves:
                errors.append(
                    f"{region}/{original}: {len(unattached_leaves)} route leaves are "
                    "not attached to a qualified LEF pin"
                )
            if "met5" in layers:
                errors.append(f"{region}/{original}: project route uses forbidden met5")
            report = reports[net_id]
            if int(report["pin_count"]) != pin_count:
                errors.append(f"{region}/{original}: wire-report pin count mismatch")
            if int(report["via_count"]) != len(vias):
                errors.append(f"{region}/{original}: wire-report via count mismatch")
            reported_geometry_length = length + extension_adjustment_um
            if abs(float(report["wire_length_um"]) - reported_geometry_length) > 0.011:
                errors.append(
                    f"{region}/{original}: DEF length {reported_geometry_length:.3f} differs from "
                    f"OpenROAD {float(report['wire_length_um']):.3f}"
                )
            hpwl = float(allocation_by_net[original]["hpwl_um"])
            ratio = length / max(hpwl, 0.001)
            if pin_count == 2 and ratio > 3.0:
                errors.append(f"{region}/{original}: two-pin detour ratio {ratio:.3f} exceeds 3.0")
            if ratio > 6.0:
                errors.append(f"{region}/{original}: route detour ratio {ratio:.3f} exceeds 6.0")
            layer_counts.update(layers)
            total_wire += length
            total_vias += len(vias)
            audited.append({
                "net": original,
                "net_id": net_id,
                "region": region,
                "pin_count": pin_count,
                "wire_length_um": round(length, 6),
                "hpwl_um": hpwl,
                "detour_ratio": round(ratio, 6),
                "via_count": len(vias),
                "layers": sorted(layers, key=LAYER_ORDER.__getitem__),
                "route_group_count": len(route_groups),
                "electrical_group_count": len(electrical_groups),
                "cycle_rank": cycle_rank,
                "leaf_count": len(leaves),
                "unattached_leaf_count": len(unattached_leaves),
                "multi_access_pin_count": sum(len(nodes) > 1 for nodes in pin_membership.values()),
            })

    routed_classes = set(jobs_report.get("policy", {}).get("route_classes", []))
    expected_original = {
        item["net"] for item in allocation["nets"]
        if item["class"] in routed_classes
    }
    if seen_original != expected_original:
        errors.append(
            "audited original-net set differs from the manifest route classes"
        )
    if len(audited) != int(jobs_report.get("total_internal_nets", -1)):
        errors.append("audited route count differs from manifest total")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "backend": jobs_report.get("backend"),
        "internal_net_count": len(audited),
        "expected_internal_net_count": len(expected_original),
        "total_wire_length_um": round(total_wire, 6),
        "total_via_count": total_vias,
        "nets_using_layer": dict(sorted(layer_counts.items(), key=lambda item: LAYER_ORDER[item[0]])),
        "maximum_route_layer": max(layer_counts, key=LAYER_ORDER.__getitem__) if layer_counts else None,
        "maximum_detour": max(audited, key=lambda item: item["detour_ratio"], default=None),
        "maximum_two_pin_detour": max(
            (item for item in audited if item["pin_count"] == 2),
            key=lambda item: item["detour_ratio"], default=None,
        ),
        "source_sha256": {
            "jobs": sha256(jobs_path),
            "allocation": sha256(allocation_path),
            "placement": sha256(placement_path),
            "mapping": sha256(mapping_path),
        },
        "artifact_sha256": {
            job["region"]: {
                name: sha256(output_root / job["region"] / filename)
                for name, filename in {
                    "routed_def": "routed.def",
                    "drc": "detailed_route_drc.rpt",
                    "log": "openroad.log",
                    "wire_length": "wire_length.csv",
                }.items()
            }
            for job in jobs_report["jobs"]
        },
        "nets": audited,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=Path, default=Path("build/v2/control_routing/openroad/openroad_jobs.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--placement", type=Path, default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--mapping", type=Path, default=Path("build/v2/control_mapping/physical_netlist.json"))
    parser.add_argument("--output-root", type=Path, default=Path("build/v2/control_routing/openroad"))
    parser.add_argument("--report", type=Path, default=Path("build/v2/control_routing/openroad/route_audit.json"))
    args = parser.parse_args()
    report = validate(
        args.jobs, args.allocation, args.placement, args.mapping, args.output_root
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "errors", "internal_net_count", "total_wire_length_um",
        "total_via_count", "nets_using_layer", "maximum_route_layer",
        "maximum_detour", "maximum_two_pin_detour",
    )}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
