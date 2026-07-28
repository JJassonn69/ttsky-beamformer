#!/usr/bin/env python3
"""Score legal first-stage phase-mux orientations from measured pin access."""

from __future__ import annotations

import argparse
import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from check_route_feasibility import component_ports


def hpwl(points: tuple[list[float], ...]) -> float:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return max(xs) - min(xs) + max(ys) - min(ys)


def minimum_tree_span(
    endpoints: list[list[list[float]]],
) -> tuple[float, list[list[float]]]:
    choices = list(itertools.product(*endpoints))
    best = min(choices, key=hpwl)
    return hpwl(best), [list(point) for point in best]


def run_study(
    template: dict[str, Any],
    dimensions: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    base = {item["name"]: item for item in template["components"]}
    candidates = []
    for name, mux_a_orientation, mux_b_orientation in (
        ("outward_outputs", "R0", "MY"),
        ("inward_outputs", "MY", "R0"),
    ):
        components = deepcopy(base)
        components["PMUX_A"]["orientation"] = mux_a_orientation
        components["PMUX_B"]["orientation"] = mux_b_orientation

        mux_a_span, mux_a_points = minimum_tree_span([
            component_ports(components["PMUX_A"], "X", dimensions, catalog),
            component_ports(components["PMUX_P"], "A0", dimensions, catalog),
            component_ports(components["PMUX_N"], "A1", dimensions, catalog),
        ])
        mux_b_span, mux_b_points = minimum_tree_span([
            component_ports(components["PMUX_B"], "X", dimensions, catalog),
            component_ports(components["PMUX_P"], "A1", dimensions, catalog),
            component_ports(components["PMUX_N"], "A0", dimensions, catalog),
        ])
        candidates.append({
            "name": name,
            "pmux_a_orientation": mux_a_orientation,
            "pmux_b_orientation": mux_b_orientation,
            "mux_a_tree_span_um": mux_a_span,
            "mux_b_tree_span_um": mux_b_span,
            "total_internal_tree_span_um": mux_a_span + mux_b_span,
            "selected_access_points": {
                "mux_a": mux_a_points,
                "mux_b": mux_b_points,
            },
            "extra_device_count": 0,
            "extra_load_count": 0,
        })

    selected = min(candidates, key=lambda item: item["total_internal_tree_span_um"])
    baseline = next(item for item in candidates if item["name"] == "outward_outputs")
    return {
        "status": "pass",
        "metric": "sum of minimum rectilinear tree bounding spans",
        "candidates": candidates,
        "selected": selected["name"],
        "reduction_vs_baseline_um_per_channel": (
            baseline["total_internal_tree_span_um"]
            - selected["total_internal_tree_span_um"]
        ),
        "constraints": [
            "R0/MY only",
            "final P/N mux orientations unchanged",
            "identical cell type and phase-input loading",
            "selection remains conditional on DRC and extracted topology",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=Path("v2/layout/channel_template.json"))
    parser.add_argument("--dimensions", type=Path, default=Path("v2/layout/pcell_dimensions.json"))
    parser.add_argument("--catalog", type=Path, default=Path("v2/layout/port_catalog.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_study(
        json.loads(args.template.read_text(encoding="utf-8")),
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
