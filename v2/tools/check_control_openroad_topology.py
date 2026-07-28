#!/usr/bin/env python3
"""Prove every extracted OpenROAD route reaches exactly its mapped cell pins."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from check_control_power_topology import logical_lines
from check_magic_rc_log import FATAL_PATTERNS


TOP = "v2_control_internal_routed"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_top(
    text: str, top: str = TOP
) -> tuple[dict[str, list[str]], list[list[str]]]:
    signatures: dict[str, list[str]] = {}
    statements: list[list[str]] = []
    active = ""
    for line in logical_lines(text):
        if line.lower().startswith(".subckt "):
            tokens = line.split()
            active = tokens[1]
            signatures[active] = tokens[2:]
        elif line.lower() == ".ends":
            active = ""
        elif active == top and line.startswith("X"):
            statements.append(line.split())
    if top not in signatures:
        raise ValueError(f"top subcircuit {top} is absent")
    return signatures, statements


def endpoint_records(counter: Counter[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {"cell": cell, "pin": pin, "count": count}
        for (cell, pin), count in sorted(counter.items())
    ]


def audit(
    spice_text: str,
    mapping: dict[str, Any],
    geometry: dict[str, Any],
    log_text: str,
    top: str = TOP,
    marker_prefix: str = "CONTROL_INTERNAL",
    handoff_extension_nets: set[str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    signatures, statements = parse_top(spice_text, top)
    label_net_map = geometry["label_net_map"]
    expected_labels = set(label_net_map)
    expected_route_count = int(geometry["counts"]["routes"])
    if len(expected_labels) != expected_route_count:
        errors.append(
            "route geometry label count differs from its routed-net count"
        )

    cell_by_instance = {
        item["instance"]: item["cell"] for item in mapping["cells"]
    }
    expected: dict[str, Counter[tuple[str, str]]] = {}
    for label, net in label_net_map.items():
        if net not in mapping["nets"]:
            errors.append(f"{label}: logical net {net} is absent from physical mapping")
            expected[label] = Counter()
            continue
        endpoints: list[tuple[str, str]] = []
        for item in mapping["nets"][net]:
            cell = cell_by_instance.get(item["instance"])
            if cell is None:
                errors.append(
                    f"{label}/{net}: endpoint instance {item['instance']} is unmapped"
                )
                continue
            endpoints.append((cell, item["pin"]))
        expected[label] = Counter(endpoints)

    actual: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    malformed_statements: list[str] = []
    for statement in statements:
        cell = statement[-1]
        signature = signatures.get(cell)
        nets = statement[1:-1]
        if signature is None or len(signature) != len(nets):
            malformed_statements.append(statement[0])
            continue
        for pin, net in zip(signature, nets):
            if net in expected_labels:
                actual[net][(cell, pin)] += 1
    if malformed_statements:
        errors.append(
            f"cannot align {len(malformed_statements)} extracted instance statements"
        )

    checks: list[dict[str, Any]] = []
    handoff_extension_nets = handoff_extension_nets or set()
    for label in sorted(expected_labels):
        logical_net = label_net_map[label]
        wanted = expected[label]
        found = actual[label]
        missing = wanted - found
        extensions = found - wanted
        extension_allowed = logical_net in handoff_extension_nets
        passed = not missing and (not extensions or extension_allowed)
        checks.append({
            "gds_label": label,
            "logical_net": logical_net,
            "status": "pass" if passed else "fail",
            "expected_endpoint_count": sum(wanted.values()),
            "actual_endpoint_count": sum(found.values()),
            "expected_endpoints": endpoint_records(wanted),
            "actual_endpoints": endpoint_records(found),
            "handoff_extension_allowed": extension_allowed,
            "extension_endpoints": endpoint_records(extensions),
        })
        if not passed:
            errors.append(
                f"{label}/{logical_net}: extracted endpoints {endpoint_records(found)} "
                f"!= mapped {endpoint_records(wanted)}"
            )

    extracted_labels = set(actual)
    missing_labels = sorted(expected_labels - extracted_labels)
    unexpected_labels = sorted(extracted_labels - expected_labels)
    if missing_labels:
        errors.append(f"extracted topology is missing route labels {missing_labels}")
    if unexpected_labels:
        errors.append(f"extracted topology has unexpected route labels {unexpected_labels}")

    fatal_matches = {
        name: pattern.search(log_text).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log_text)
    }
    if fatal_matches:
        errors.append(f"Magic extraction log has fatal markers: {fatal_matches}")
    required_markers = (
        f"{marker_prefix}_EXTRACTION_DRC_COUNT=0",
        f"{marker_prefix}_EXTRACTION_FEEDBACK_COUNT=0",
        f"{marker_prefix}_HIER_SPICE=",
        f"{marker_prefix}_FLAT_SPICE=",
    )
    missing_markers = [item for item in required_markers if item not in log_text]
    if missing_markers:
        errors.append(f"Magic extraction log lacks markers {missing_markers}")
    if log_text.count("exttospice finished.") < 2:
        errors.append("Magic did not complete both topology netlists")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "route_count": len(checks),
        "verified_route_count": sum(item["status"] == "pass" for item in checks),
        "expected_endpoint_count": sum(
            item["expected_endpoint_count"] for item in checks
        ),
        "verified_endpoint_count": sum(
            item["actual_endpoint_count"] for item in checks
            if item["status"] == "pass"
        ),
        "extracted_unique_route_label_count": len(extracted_labels),
        "missing_route_labels": missing_labels,
        "unexpected_route_labels": unexpected_labels,
        "malformed_instance_statement_count": len(malformed_statements),
        "magic_log_fatal_matches": fatal_matches,
        "magic_exttospice_completion_count": log_text.count("exttospice finished."),
        "routes": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spice", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/extraction/control_internal_hier.spice"),
    )
    parser.add_argument(
        "--mapping", type=Path,
        default=Path("build/v2/control_mapping/physical_netlist.json"),
    )
    parser.add_argument(
        "--geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    parser.add_argument(
        "--log", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/magic_extraction.log"),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/control_routing/openroad_internal/extraction/topology_audit.json"),
    )
    parser.add_argument("--top", default=TOP)
    parser.add_argument("--marker-prefix", default="CONTROL_INTERNAL")
    parser.add_argument(
        "--handoff-allocation", type=Path,
        help=(
            "allow additional extracted endpoints only on trim, phase, and "
            "quadrature handoff nets from this allocation; dedicated stage "
            "audits must validate those extensions"
        ),
    )
    args = parser.parse_args()
    handoff_extensions: set[str] = set()
    if args.handoff_allocation:
        allocation = json.loads(args.handoff_allocation.read_text(encoding="utf-8"))
        handoff_extensions = {
            item["net"] for item in allocation["nets"]
            if item["class"] in {
                "trim_handoff", "phase_handoff", "quadrature_handoff"
            }
        }
    report = audit(
        args.spice.read_text(encoding="utf-8", errors="replace"),
        json.loads(args.mapping.read_text(encoding="utf-8")),
        json.loads(args.geometry.read_text(encoding="utf-8")),
        args.log.read_text(encoding="utf-8", errors="replace"),
        args.top,
        args.marker_prefix,
        handoff_extensions,
    )
    report["evidence_sha256"] = {
        "spice": sha256(args.spice),
        "mapping": sha256(args.mapping),
        "geometry": sha256(args.geometry),
        "magic_log": sha256(args.log),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
