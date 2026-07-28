#!/usr/bin/env python3
"""Check critical V2 route spans against measured, oriented terminal ports."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def manhattan(first: list[float], second: list[float]) -> float:
    return abs(first[0] - second[0]) + abs(first[1] - second[1])


def component_ports(
    component: dict[str, Any],
    terminal: str,
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[list[float]]:
    pcell = component["pcell"]
    orientation = component["orientation"]
    cx, cy = float(component["x"]), float(component["y"])
    if pcell.startswith("sc_hd_"):
        width = float(dimensions["pcells"][pcell]["width_um"])
        height = float(dimensions["pcells"][pcell]["height_um"])
        records = catalog["standard_cells"][pcell]["ports"][terminal]
        points = [record["center_um"] for record in records]
        if orientation == "R0":
            return [[cx + x - width / 2.0, cy + y - height / 2.0] for x, y in points]
        if orientation == "MY":
            return [[cx + width / 2.0 - x, cy + y - height / 2.0] for x, y in points]
    else:
        records = catalog["analog_pcells"][pcell]["ports"][terminal]
        points = [record["point_um"] for record in records]
        if orientation == "R0":
            return [[cx + x, cy + y] for x, y in points]
        if orientation == "MY":
            return [[cx - x, cy + y] for x, y in points]
    raise ValueError(f"unsupported orientation {orientation} for {component['name']}")


def resolve(
    endpoint: dict[str, Any],
    target: list[float],
    components: dict[str, dict[str, Any]],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> list[float]:
    if "anchor" in endpoint:
        return list(map(float, endpoint["anchor"]))
    candidates = component_ports(
        components[endpoint["component"]], endpoint["terminal"], dimensions, catalog
    )
    if "expected_point_um" in endpoint:
        expected = list(map(float, endpoint["expected_point_um"]))
        if not any(math.dist(expected, candidate) < 1e-9 for candidate in candidates):
            raise ValueError(
                f"{endpoint['component']}.{endpoint['terminal']} expected port {expected} "
                f"not in measured candidates {candidates}"
            )
        return expected
    return min(candidates, key=lambda point: manhattan(point, target))


def validate(
    plan: dict[str, Any],
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    components = {component["name"]: component for component in template["components"]}
    reports: dict[str, Any] = {}
    for tree in plan["trees"]:
        try:
            provisional_target = (
                list(map(float, tree["root"].get("anchor", [1.0, 72.0])))
                if isinstance(tree["root"], dict)
                else [1.0, 72.0]
            )
            root = resolve(tree["root"], provisional_target, components, dimensions, catalog)
            endpoints = [
                {
                    "name": terminal.get(
                        "name", f"{terminal.get('component')}.{terminal.get('terminal')}"
                    ),
                    "point_um": resolve(terminal, root, components, dimensions, catalog),
                }
                for terminal in tree["terminals"]
            ]
        except (KeyError, ValueError) as error:
            errors.append(f"{tree['name']}: {error}")
            continue
        distances = [manhattan(root, endpoint["point_um"]) for endpoint in endpoints]
        maximum = max(distances)
        budget = float(tree["max_root_to_terminal_um"])
        if maximum > budget + 1e-9:
            errors.append(
                f"{tree['name']}: terminal span {maximum:.3f} um exceeds {budget:.3f} um"
            )
        reports[tree["name"]] = {
            "class": tree["class"],
            "root_um": root,
            "terminals": endpoints,
            "endpoint_count": len(endpoints),
            "max_root_manhattan_um": maximum,
            "total_root_manhattan_um": sum(distances),
            "budget_um": budget,
            "margin_um": budget - maximum,
        }

    matching: dict[str, Any] = {}
    for group in plan["matching_groups"]:
        first_name, second_name = group["trees"]
        if first_name not in reports or second_name not in reports:
            errors.append(f"{group['name']}: missing route-tree report")
            continue
        first, second = reports[first_name], reports[second_name]
        if first["endpoint_count"] != second["endpoint_count"]:
            errors.append(f"{group['name']}: endpoint counts differ")
        first_total = first["total_root_manhattan_um"]
        second_total = second["total_root_manhattan_um"]
        mismatch = 100.0 * abs(first_total - second_total) / max(first_total, second_total)
        limit = float(group["max_total_mismatch_percent"])
        if mismatch > limit + 1e-12:
            errors.append(
                f"{group['name']}: pre-route demand mismatch {mismatch:.6f}% exceeds {limit:.6f}%"
            )
        matching[group["name"]] = {
            "trees": [first_name, second_name],
            "total_root_manhattan_um": [first_total, second_total],
            "mismatch_percent": mismatch,
            "limit_percent": limit,
        }

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "trees": reports,
        "matching_groups": matching,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.template.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
