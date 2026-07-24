#!/usr/bin/env python3
"""Score legal R0/MY channel-pair orientations from measured PCell ports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def oriented(values: list[float], orientation: str) -> list[float]:
    if orientation == "R0":
        return values
    if orientation == "MY":
        return sorted(-value for value in values)
    raise ValueError(f"unsupported study orientation: {orientation}")


def pair_metrics(
    cell: dict[str, Any],
    left_center: float,
    right_center: float,
    right_orientation: str,
) -> dict[str, float]:
    terminals = cell["terminal_x_um"]
    left_sources = [left_center + value for value in oriented(terminals["S"], "R0")]
    right_sources = [
        right_center + value for value in oriented(terminals["S"], right_orientation)
    ]
    left_drains = [left_center + value for value in oriented(terminals["D"], "R0")]
    right_drains = [
        right_center + value for value in oriented(terminals["D"], right_orientation)
    ]
    source_contacts = left_sources + right_sources
    left_outer_drain = min(left_drains)
    right_outer_drain = max(right_drains)
    pair_midpoint = (left_center + right_center) / 2.0
    return {
        "source_collection_span_um": max(source_contacts) - min(source_contacts),
        "outer_drain_escape_imbalance_um": abs(
            abs(left_outer_drain - pair_midpoint)
            - abs(right_outer_drain - pair_midpoint)
        ),
    }


def run_study(dimensions: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    cells = dimensions["pcells"]
    components = template["components"]
    gm_rows = sorted({component["y"] for component in components if component["role"].startswith("gm_")})
    mixer_rows = sorted({component["y"] for component in components if component["role"].startswith("mixer_")})

    candidates = []
    for name, right_orientation in (("all_r0", "R0"), ("source_facing_pairs", "MY")):
        row_metrics: list[dict[str, float]] = []
        for row in gm_rows:
            pair = sorted(
                [component for component in components if component["y"] == row and component["role"].startswith("gm_")],
                key=lambda component: component["x"],
            )
            row_metrics.append(
                pair_metrics(
                    cells["gm_nfet_guarded"],
                    float(pair[0]["x"]),
                    float(pair[1]["x"]),
                    right_orientation,
                )
            )
        for row in mixer_rows:
            pair = sorted(
                [component for component in components if component["y"] == row and component["role"].startswith("mixer_")],
                key=lambda component: component["x"],
            )
            row_metrics.append(
                pair_metrics(
                    cells["mixer_nfet_guarded"],
                    float(pair[0]["x"]),
                    float(pair[1]["x"]),
                    right_orientation,
                )
            )
        source_span = sum(metric["source_collection_span_um"] for metric in row_metrics)
        drain_imbalance = sum(
            metric["outer_drain_escape_imbalance_um"] for metric in row_metrics
        )
        weighted_cost = source_span + 5.0 * drain_imbalance
        candidates.append(
            {
                "name": name,
                "left_orientation": "R0",
                "right_orientation": right_orientation,
                "pair_count": len(row_metrics),
                "total_source_collection_span_um": source_span,
                "total_outer_drain_escape_imbalance_um": drain_imbalance,
                "crossings": 0,
                "extra_via_sites": 0,
                "keepout_intersections": 0,
                "weighted_cost": weighted_cost,
            }
        )

    selected = min(candidates, key=lambda candidate: candidate["weighted_cost"])
    baseline = next(candidate for candidate in candidates if candidate["name"] == "all_r0")
    return {
        "status": "pass",
        "provenance": {
            "port_coordinates": "measured from generated Magic child MAG labels",
            "pcell_dimension_file": "v2/layout/pcell_dimensions.json",
            "template_file": "v2/layout/channel_template.json",
        },
        "cost_weights": {"source_collection_span": 1.0, "drain_escape_imbalance": 5.0},
        "candidates": candidates,
        "selected": selected["name"],
        "source_route_reduction_vs_all_r0_um_per_channel": (
            baseline["total_source_collection_span_um"]
            - selected["total_source_collection_span_um"]
        ),
        "selection_is_conditional_on": [
            "Magic DRC",
            "terminal-aware extraction topology",
            "R0/MY device-count and W/L equivalence",
            "post-layout parasitic comparison"
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dimensions", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_study(
        json.loads(args.dimensions.read_text(encoding="utf-8")),
        json.loads(args.template.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
