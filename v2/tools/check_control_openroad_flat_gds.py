#!/usr/bin/env python3
"""Compare independent flattened rules before and after internal routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from check_gds_flat_rules import (  # noqa: E402
    CAPM,
    MET3,
    MET4,
    VIA3,
    audit_rectangles,
    flatten_rectangles,
    parse_gds,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(
    source: Path,
    source_top: str,
    candidate: Path,
    candidate_top: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    source_structures, source_dbu = parse_gds(source)
    candidate_structures, candidate_dbu = parse_gds(candidate)
    source_rectangles = flatten_rectangles(
        source_structures, source_top, source_dbu
    )
    candidate_rectangles = flatten_rectangles(
        candidate_structures, candidate_top, candidate_dbu
    )
    source_components, source_checks = audit_rectangles(source_rectangles)
    candidate_components, candidate_checks = audit_rectangles(candidate_rectangles)

    inherited = {name: values for name, values in source_checks.items() if values}
    if not (
        set(inherited) == {"met4 minimum width"}
        and len(inherited["met4 minimum width"]) == 1
        and abs(inherited["met4 minimum width"][0] - 0.20) <= 1e-9
    ):
        errors.append(f"unexpected frozen-source marker set: {inherited}")
    if candidate_checks != source_checks:
        errors.append("internal routing changes the independent flattened marker set")
    if sha256(source) != plan["source_checkpoint"]["sha256"]:
        errors.append("flattened-audit source differs from frozen route checkpoint")
    if plan["maximum_route_layer"] != "met4":
        errors.append("route contract does not record intentional service-pin M4 use")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "policy": (
            "internal routing may add no flattened-rule marker; M4 is limited "
            "to the thirteen legal external input and service-pin routes"
        ),
        "source_gds": str(source),
        "source_sha256": sha256(source),
        "candidate_gds": str(candidate),
        "candidate_sha256": sha256(candidate),
        "inherited_marker_count_by_rule": {
            name: len(values) for name, values in source_checks.items()
        },
        "candidate_marker_count_by_rule": {
            name: len(values) for name, values in candidate_checks.items()
        },
        "source_geometry": {
            "met3_rectangles": len(source_rectangles[MET3]),
            "met3_components": len(source_components[MET3]),
            "via3_cuts": len(source_rectangles[VIA3]),
            "met4_rectangles": len(source_rectangles[MET4]),
            "met4_components": len(source_components[MET4]),
            "capm_components": len(source_components[CAPM]),
        },
        "candidate_geometry": {
            "met3_rectangles": len(candidate_rectangles[MET3]),
            "met3_components": len(candidate_components[MET3]),
            "via3_cuts": len(candidate_rectangles[VIA3]),
            "met4_rectangles": len(candidate_rectangles[MET4]),
            "met4_components": len(candidate_components[MET4]),
            "capm_components": len(candidate_components[CAPM]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        default=Path("build/v2/control_power/direct/v2_four_channel_control_powered.gds"),
    )
    parser.add_argument("--source-top", default="v2_four_channel_control_powered")
    parser.add_argument(
        "--candidate", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/direct/v2_control_internal_routed.gds"),
    )
    parser.add_argument("--candidate-top", default="v2_control_internal_routed")
    parser.add_argument(
        "--plan", type=Path,
        default=Path("v2/layout/control_openroad_route_plan.json"),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/flat_gds_audit.json"),
    )
    args = parser.parse_args()
    report = audit(
        args.source,
        args.source_top,
        args.candidate,
        args.candidate_top,
        json.loads(args.plan.read_text(encoding="utf-8")),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
