#!/usr/bin/env python3
"""Check the extracted topology of the exact V3 VCM support pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETLIST = ROOT / "build" / "v3" / "vcm_support_pilot" / "v3_vcm_support_pilot_flat.spice"
DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "shared_support_placement.json"
DEFAULT_GDS = ROOT / "build" / "v3" / "vcm_support_pilot" / "v3_vcm_support_pilot.gds"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "vcm_support_topology_check.json"
RES_MODEL = "sky130_fd_pr__res_xhigh_po_1p41"
CAP_MODEL = "sky130_fd_pr__cap_mim_m3_1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resistors = []
    capacitors = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        fields = line.split()
        if RES_MODEL in fields:
            index = fields.index(RES_MODEL)
            if index != 4:
                raise ValueError(f"unexpected resistor record: {line}")
            resistors.append({
                "instance": fields[0],
                "terminals": fields[1:3],
                "body": fields[3],
                "parameters": fields[5:],
            })
        elif CAP_MODEL in fields:
            index = fields.index(CAP_MODEL)
            if index != 3:
                raise ValueError(f"unexpected capacitor record: {line}")
            capacitors.append({
                "instance": fields[0],
                "terminals": fields[1:3],
                "parameters": fields[4:],
            })
    return resistors, capacitors


def shortest_edge_count(
    graph: dict[str, list[str]], start: str, stop: str
) -> int | None:
    pending = deque([(start, 0)])
    visited = set()
    while pending:
        node, distance = pending.popleft()
        if node == stop:
            return distance
        if node in visited:
            continue
        visited.add(node)
        pending.extend((neighbor, distance + 1) for neighbor in graph[node])
    return None


def check(netlist: Path, manifest: Path, gds: Path = DEFAULT_GDS) -> dict[str, Any]:
    placement = json.loads(manifest.read_text(encoding="utf-8"))
    resistors, capacitors = parse(netlist)
    errors: list[str] = []
    graph: dict[str, list[str]] = defaultdict(list)
    for item in resistors:
        first, second = item["terminals"]
        graph[first].append(second)
        graph[second].append(first)
        if item["body"] != "VGND":
            errors.append(f"{item['instance']} body is {item['body']}, not VGND")
    top_edges = shortest_edge_count(graph, "VDPWR", "vcm")
    bottom_edges = shortest_edge_count(graph, "vcm", "VGND")
    expected_caps = len(placement["vcm"]["bypass_capacitors"])
    if len(resistors) != 6:
        errors.append(f"expected six divider resistors, found {len(resistors)}")
    if len(capacitors) != expected_caps:
        errors.append(f"expected {expected_caps} VCM MIMs, found {len(capacitors)}")
    if top_edges != 2:
        errors.append(f"VDPWR-to-vcm divider path has {top_edges} units, expected 2")
    if bottom_edges != 4:
        errors.append(f"vcm-to-VGND divider path has {bottom_edges} units, expected 4")
    for item in capacitors:
        if set(item["terminals"]) != {"vcm", "VGND"}:
            errors.append(
                f"{item['instance']} terminals are {item['terminals']}, expected vcm/VGND"
            )
    internal_degrees = {
        node: len(neighbors)
        for node, neighbors in graph.items()
        if node not in {"VDPWR", "vcm", "VGND"}
    }
    if any(degree != 2 for degree in internal_degrees.values()):
        errors.append(f"divider internal node degree changed: {internal_degrees}")
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "resistor_count": len(resistors),
        "capacitor_count": len(capacitors),
        "top_series_unit_count": top_edges,
        "bottom_series_unit_count": bottom_edges,
        "all_resistor_bodies_grounded": all(
            item["body"] == "VGND" for item in resistors
        ),
        "all_capacitors_connect_vcm_to_ground": all(
            set(item["terminals"]) == {"vcm", "VGND"}
            for item in capacitors
        ),
        "internal_resistor_node_degrees": internal_degrees,
        "provenance": {
            "netlist": str(netlist.relative_to(ROOT)),
            "netlist_sha256": sha256(netlist),
            "gds": str(gds.relative_to(ROOT)),
            "gds_sha256": sha256(gds),
            "manifest": str(manifest.relative_to(ROOT)),
            "manifest_sha256": sha256(manifest),
            "generator": "v3/tools/check_vcm_support_extraction.py",
            "generator_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netlist", type=Path, default=DEFAULT_NETLIST)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = check(args.netlist, args.manifest, args.gds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
