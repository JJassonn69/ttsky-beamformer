#!/usr/bin/env python3
"""Validate V3 shared-support placement and route constraints."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3" / "layout" / "shared_support_placement.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "shared_support_placement_check.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def overlap(first: list[float], second: list[float]) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def contains(outer: list[float], inner: list[float]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def connected(segments: list[dict[str, Any]]) -> bool:
    if not segments:
        return False
    graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for item in segments:
        start = tuple(item["from"])
        stop = tuple(item["to"])
        if start == stop:
            return False
        graph[start].add(stop)
        graph[stop].add(start)
    visited = set()
    pending = [next(iter(graph))]
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(graph[node] - visited)
    return visited == set(graph)


def route_groups(data: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups = []
    for index, item in enumerate(data["vcm"]["divider_internal_routes"]):
        groups.append((f"vcm.divider_internal_routes[{index}]", item["segments"]))
    groups.append(("vcm.feed", data["vcm"]["feed"]["segments"]))
    groups.append(("vcm.ground", data["vcm"]["ground"]["segments"]))
    for name, item in data["tail_bias"]["routes"].items():
        groups.append((f"tail_bias.routes.{name}", item["segments"]))
    return groups


def check(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    provenance = data["provenance"]
    for key, hash_key in (
        ("floorplan", "floorplan_sha256"),
        ("pcell_catalog", "pcell_catalog_sha256"),
        ("shared_support_candidate_selection", "shared_support_candidate_selection_sha256"),
        ("bias_distribution", "bias_distribution_sha256"),
        ("input_bias_distribution", "input_bias_distribution_sha256"),
    ):
        path = ROOT / provenance[key]
        if sha256(path) != provenance[hash_key]:
            errors.append(f"stale provenance: {key}")

    floorplan = json.loads((ROOT / provenance["floorplan"]).read_text(encoding="utf-8"))
    zones = {item["name"]: item["bbox"] for item in floorplan["zones"]}
    components = (
        data["vcm"]["divider_units"]
        + data["vcm"]["bypass_capacitors"]
        + data["output_pair"]["components"]
        + [data["tail_bias"]["bias_resistor"]]
        + data["tail_bias"]["bypass_capacitors"]
    )
    if len({item["name"] for item in components}) != len(components):
        errors.append("component names are not unique")
    for index, first in enumerate(components):
        for second in components[index + 1:]:
            if overlap(first["bbox"], second["bbox"]):
                errors.append(f"component overlap: {first['name']}/{second['name']}")

    for item in data["vcm"]["divider_units"] + data["vcm"]["bypass_capacitors"]:
        if not contains(zones["shared_vcm"], item["bbox"]):
            errors.append(f"{item['name']} is outside shared_vcm")
    for item in data["output_pair"]["components"]:
        if not contains(zones["differential_load_pair"], item["bbox"]):
            errors.append(f"{item['name']} is outside differential_load_pair")
    for item in [data["tail_bias"]["bias_resistor"]] + data["tail_bias"]["bypass_capacitors"]:
        if not contains(zones["shared_tail_bias_and_decap"], item["bbox"]):
            errors.append(f"{item['name']} is outside shared_tail_bias_and_decap")

    divider = data["vcm"]["divider_units"]
    groups: dict[str, list[list[float]]] = defaultdict(list)
    for item in divider:
        groups[item["role"].removeprefix("vcm_divider_")].append(item["center"])
    centroids = {
        group: [
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        ]
        for group, points in groups.items()
    }
    if set(groups) != {"A", "B"} or len(groups["A"]) != 2 or len(groups["B"]) != 4:
        errors.append("VCM divider is not a 2:4 six-unit assignment")
    elif any(
        not math.isclose(a, b, abs_tol=1e-9)
        for a, b in zip(centroids["A"], centroids["B"])
    ):
        errors.append(f"VCM A/B centroids differ: {centroids}")

    if len(data["vcm"]["bypass_capacitors"]) != 3:
        errors.append("selected VCM bypass must contain exactly three MIMs")
    if data["vcm"]["varactor_count"] != 0:
        errors.append("selected VCM bypass unexpectedly contains a varactor")
    if len(data["output_pair"]["components"]) != 2:
        errors.append("differential output load pair count changed")
    if len(data["tail_bias"]["bypass_capacitors"]) != 2:
        errors.append("tail-bias bypass must contain exactly two MIMs")

    route_status = {}
    for name, segments in route_groups(data):
        orthogonal = all(
            math.isclose(item["from"][0], item["to"][0], abs_tol=1e-9)
            or math.isclose(item["from"][1], item["to"][1], abs_tol=1e-9)
            for item in segments
        )
        is_connected = connected(segments)
        route_status[name] = {
            "segment_count": len(segments),
            "all_manhattan": orthogonal,
            "connected": is_connected,
        }
        if not orthogonal:
            errors.append(f"non-Manhattan route group: {name}")
        if not is_connected:
            errors.append(f"disconnected or zero-length route group: {name}")

    feed = data["vcm"]["feed"]
    if feed["direction_reversals"] != 0:
        errors.append("VCM feed permits direction reversal")
    if any(item["layer"] != "metal4" for item in feed["segments"]):
        errors.append("VCM common feed must cross the output trunks only on Metal 4")
    if any(data["layout_invariants"][name] for name in (
        "metal5_used", "floating_stubs_allowed", "orphan_vias_allowed",
        "u_turns_or_meanders_allowed",
    )):
        errors.append("a prohibited shared-support layout behavior is enabled")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "component_count": len(components),
        "vcm_divider_centroids_um": centroids,
        "vcm_bypass_mim_count": len(data["vcm"]["bypass_capacitors"]),
        "tail_bypass_mim_count": len(data["tail_bias"]["bypass_capacitors"]),
        "route_groups": route_status,
        "physical_geometry_status": "pending exact Magic pilot",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = check(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
