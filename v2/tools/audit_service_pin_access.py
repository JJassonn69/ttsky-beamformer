#!/usr/bin/env python3
"""Prove every service pin has a direct-via route against the frozen source.

This isolates pin-access failures from service-to-service congestion.  It is a
fail-fast floorplanning gate: an earlier stage must move if any future service
pin cannot lift at its named LEF port with zero lateral M1 routing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from generate_control_service_routes import (
    _source_index, allocate_row_tracks, branch_key, choose_pin_escape,
)

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from check_gds_flat_rules import (  # noqa: E402
    MET1, flatten_orthogonal_rectangles, flatten_rectangles, parse_gds,
)


def audit(plan: dict[str, Any], allocation: dict[str, Any],
          catalog: dict[str, Any], root: Path) -> dict[str, Any]:
    records = {
        item["net"]: item for item in allocation["nets"]
        if item["class"] == "service_tree"
    }
    catalog_by_key = {
        (item["instance"], item["pin"]): item for item in catalog["records"]
    }
    structures, database_um = parse_gds(root / plan["source_checkpoint"]["gds"])
    rectangles = flatten_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um
    )
    rectangles[MET1] = flatten_orthogonal_rectangles(
        structures, plan["source_checkpoint"]["top"], database_um, {MET1}
    )[MET1]
    source = _source_index(rectangles)
    row_tracks = allocate_row_tracks(plan, records)
    failures: list[dict[str, Any]] = []
    successes: list[dict[str, Any]] = []
    for net, record in sorted(records.items()):
        endpoints = sorted(
            (item for item in record["endpoints"]
             if item["kind"] == "standard_cell_pin"),
            key=lambda item: (
                item["region"], int(item["row"]), float(item["point_um"][0])
            ),
        )
        for endpoint in endpoints:
            region, group, track_y = branch_key(plan, net, endpoint, row_tracks)
            key = (endpoint["instance"], endpoint["pin"])
            try:
                selected = choose_pin_escape(
                    net, endpoint, catalog_by_key[key], track_y, plan, source, []
                )
            except ValueError as error:
                failures.append({
                    "net": net, "instance": key[0], "pin": key[1],
                    "region": region, "row": endpoint["row"],
                    "error": str(error),
                })
                continue
            successes.append({
                "net": net, "instance": key[0], "pin": key[1],
                "pin_layer": selected["pin_layer"],
                "pin_um": selected["pin_um"], "lift_um": selected["lift_um"],
                "m1_escape_manhattan_um": selected["m1_escape_manhattan_um"],
            })
    layers = Counter(item["pin_layer"] for item in successes)
    errors = [item["error"] for item in failures]
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "mapped_service_pin_count": len(successes) + len(failures),
        "source_legal_direct_via_count": len(successes),
        "source_blocked_pin_count": len(failures),
        "selected_access_layer_count": dict(sorted(layers.items())),
        "failures": failures,
        "accesses": successes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path,
                        default=Path("v2/layout/control_service_route_plan.json"))
    parser.add_argument("--allocation", type=Path,
                        default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--catalog", type=Path,
                        default=Path("build/v2/control_routing/control_pin_access_catalog.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("build/v2/control_routing/service_pin_access_audit.json"))
    args = parser.parse_args()
    report = audit(
        json.loads(args.plan.read_text()),
        json.loads(args.allocation.read_text()),
        json.loads(args.catalog.read_text()), ROOT,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in (
        "status", "mapped_service_pin_count", "source_legal_direct_via_count",
        "source_blocked_pin_count", "selected_access_layer_count", "failures",
    )}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
