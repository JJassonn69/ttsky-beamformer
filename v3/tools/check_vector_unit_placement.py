#!/usr/bin/env python3
"""Validate the V3 vector-unit placement and route contract."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3" / "layout" / "vector_unit_placement.json"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "vector_unit_placement_check.json"


def overlap(a: list[float], b: list[float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def route_connected(segments: list[dict[str, Any]]) -> bool:
    graph: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for item in segments:
        a, b = tuple(item["from"]), tuple(item["to"])
        graph[a].add(b)
        graph[b].add(a)
    pending = deque([next(iter(graph))])
    seen = set()
    while pending:
        node = pending.popleft()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(graph[node] - seen)
    return seen == set(graph)


def check(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    tile = data["tile_bbox"]
    devices = data["devices"]
    for item in devices:
        box = item["bbox"]
        if box[0] < tile[0] or box[1] < tile[1] or box[2] > tile[2] or box[3] > tile[3]:
            errors.append(f"{item['name']} exceeds tile: {box}")
    for index, first in enumerate(devices):
        for second in devices[index + 1 :]:
            if overlap(first["bbox"], second["bbox"]):
                errors.append(f"device overlap: {first['name']} / {second['name']}")
    route_status = {}
    for name, segments in data["routes"].items():
        manhattan = all(
            item["from"][0] == item["to"][0] or item["from"][1] == item["to"][1]
            for item in segments
        )
        connected = route_connected(segments)
        route_status[name] = {"manhattan": manhattan, "connected": connected, "segment_count": len(segments)}
        if not manhattan:
            errors.append(f"{name} contains non-Manhattan segment")
        if not connected:
            errors.append(f"{name} route graph is disconnected")
    counts = defaultdict(int)
    for item in devices:
        counts[item["cell"]] += 1
    if dict(counts) != {"XTAIL_U": 1, "XGM_U": 2, "XSW_U": 4}:
        errors.append(f"device population changed: {dict(counts)}")
    if set(data["boundary_ports"]) != {
        "sig", "ref", "vbias", "VGND", "lop_left", "lop_right",
        "lon_left", "lon_right", "outp", "outn",
    }:
        errors.append("boundary port contract changed")
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "device_counts": dict(counts),
        "route_status": route_status,
        "tile_bbox": tile,
        "physical_status": "pending exact Magic unit pilot",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = check(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
