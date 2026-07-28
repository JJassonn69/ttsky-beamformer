#!/usr/bin/env python3
"""Audit final-control distributed metal-RC extraction and route coverage."""

from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_distributed_rc import annotation_counts, rc_details, spice_elements
from tools.check_distributed_rc import INTERNAL_NODE_RE
from v2.tools.check_magic_rc_log import FATAL_PATTERNS
from v2.tools.check_support_rc import required_routed_nets as required_analog_nets


def required_routed_nets(allocation: dict[str, Any]) -> set[str]:
    control = {
        item["net"] for item in allocation["nets"]
        if item["class"] in ("direct_boundary", "service_tree")
    }
    return control | required_analog_nets() | {"VDPWR"}


def _marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


EQUIV_RE = re.compile(r'^equiv "([^"]+)" "([^"]+)"')
MINIMUM_RESISTOR_EMISSION_RATIO = 0.90


def equivalence_alias_coverage(
    top_ext_path: Path,
    rc: dict[str, list[list[str]]],
    uncovered_nets: list[str],
) -> dict[str, dict[str, Any]]:
    """Prove RC coverage when ext2spice canonicalizes a named top-level net.

    Magic can emit a routed supply's resistor graph under an electrically
    equivalent flattened-cell bulk name.  For example, the final VGND graph
    is rooted at a standard-cell ``VNB`` node even though the source label is
    ``v2_control_power_overlay_0.VGND``.  This routine accepts that alias only
    when the ordinary ``.ext`` file contains a complete equivalence path from
    a node ending in the required name to a node used by an emitted resistor.
    """

    adjacency: dict[str, set[str]] = {}
    for raw_line in top_ext_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        match = EQUIV_RE.match(raw_line)
        if not match:
            continue
        first, second = match.groups()
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    resistor_bases = Counter(
        INTERNAL_NODE_RE.sub("", node)
        for fields in rc["R"]
        if len(fields) >= 3
        for node in fields[1:3]
    )
    proofs: dict[str, dict[str, Any]] = {}
    for net in uncovered_nets:
        suffixes = (f".{net}", f"/{net}")
        seeds = sorted(
            node for node in adjacency
            if node == net or node.endswith(suffixes)
        )
        if not seeds:
            continue
        preferred = f"v2_control_power_overlay_0.{net}"
        if preferred in seeds:
            seeds.remove(preferred)
            seeds.insert(0, preferred)

        queue = deque(seeds)
        previous: dict[str, str | None] = {seed: None for seed in seeds}
        found: list[str] = []
        while queue:
            node = queue.popleft()
            if node in resistor_bases:
                found.append(node)
            for neighbor in sorted(adjacency.get(node, ())):
                if neighbor not in previous:
                    previous[neighbor] = node
                    queue.append(neighbor)
        if not found:
            continue

        alias = max(found, key=lambda node: (resistor_bases[node], node))
        path = [alias]
        while previous[path[-1]] is not None:
            path.append(previous[path[-1]])
        path.reverse()
        proofs[net] = {
            "source_extracted_node": path[0],
            "resistor_graph_alias": alias,
            "resistor_terminal_occurrences": resistor_bases[alias],
            "equivalence_path": path,
        }
    return proofs


def audit(base_path: Path, rc_path: Path, res_ext_path: Path,
          allocation: dict[str, Any], log: str) -> dict[str, Any]:
    base = spice_elements(base_path)
    rc = spice_elements(rc_path)
    required = required_routed_nets(allocation)
    details = rc_details(rc, required)
    rnodes, annotated = annotation_counts(res_ext_path)
    emitted_ratio = details["resistors"] / annotated if annotated else 0.0
    top_ext = res_ext_path.with_name(
        res_ext_path.name.removesuffix(".res.ext") + ".ext"
    )
    alias_coverage = equivalence_alias_coverage(
        top_ext, rc, details["uncovered_manifest_nets"]
    ) if top_ext.is_file() else {}
    uncovered = sorted(
        set(details["uncovered_manifest_nets"]) - set(alias_coverage)
    )
    fatal = {
        name: pattern.search(log).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)
    }
    output_markers = all(
        re.search(rf"^{name}=\S+\s*$", log, flags=re.MULTILINE)
        for name in (
            "CONTROL_SERVICE_BASE_SPICE", "CONTROL_SERVICE_RC_SPICE",
            "CONTROL_SERVICE_RES_EXT",
        )
    )
    checks = {
        "magic_drc_clean": _marker(log, "CONTROL_SERVICE_RC_DRC_COUNT") == 0,
        "magic_feedback_clean": _marker(
            log, "CONTROL_SERVICE_RC_EXTRACTION_FEEDBACK_COUNT"
        ) == 0,
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 and output_markers,
        "no_silent_magic_failures": not fatal,
        "base_is_resistance_free_reference": len(base["R"]) == 0,
        "resistance_annotation_exists": rnodes > 0 and annotated > 0,
        "resistance_annotation_is_fresh": (
            top_ext.is_file()
            and res_ext_path.stat().st_mtime_ns >= top_ext.stat().st_mtime_ns
        ),
        "explicit_resistors_emitted": (
            annotated > 0 and emitted_ratio >= MINIMUM_RESISTOR_EMISSION_RATIO
        ),
        "distributed_capacitances_emitted": details["capacitors"] > len(base["C"]),
        "device_count_preserved": details["devices"] == len(base["X"]) > 0,
        "all_control_analog_and_power_routes_resistively_covered": not uncovered,
        "internal_resistor_nodes_emitted": details["internal_resistor_nodes"] >= len(required),
        "resistor_records_well_formed": not details["malformed_resistors"],
        "resistor_values_positive": not details["nonpositive_resistors"],
        "no_extraction_attribute_nodes": not details["attribute_like_resistor_nodes"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "required_routed_net_count": len(required),
        "required_routed_nets": sorted(required),
        "uncovered_routed_nets": uncovered,
        "equivalence_alias_coverage": alias_coverage,
        "base": {"resistors": len(base["R"]), "capacitors": len(base["C"]), "devices": len(base["X"])},
        "distributed_rc": details,
        "annotation": {
            "rnodes": rnodes,
            "resistors": annotated,
            "spice_to_annotation_ratio": emitted_ratio,
            "minimum_spice_to_annotation_ratio": MINIMUM_RESISTOR_EMISSION_RATIO,
        },
        "magic_fatal_matches": fatal,
        "sha256": {
            "base": hashlib.sha256(base_path.read_bytes()).hexdigest(),
            "distributed_rc": hashlib.sha256(rc_path.read_bytes()).hexdigest(),
            "resistance_annotation": hashlib.sha256(res_ext_path.read_bytes()).hexdigest(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    work = Path("build/v2/control_routing/control_service_rc")
    parser.add_argument("--base", type=Path, default=work / "control_service_base.spice")
    parser.add_argument("--rc", type=Path, default=work / "control_service_rc.spice")
    parser.add_argument("--res-ext", type=Path, default=work / "v2_control_service_routed_rc_flat.res.ext")
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--log", type=Path, default=work / "magic_rc.log")
    parser.add_argument("--report", type=Path, default=work / "coverage_audit.json")
    args = parser.parse_args()
    report = audit(
        args.base, args.rc, args.res_ext,
        json.loads(args.allocation.read_text()),
        args.log.read_text(errors="replace"),
    )
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    details = report["distributed_rc"]
    print(
        "Final-chip distributed-RC "
        + ("passed" if report["passed"] else "FAILED")
        + f": {details['resistors']} resistors, {details['capacitors']} capacitors, "
        + f"{details['devices']} devices, "
        + f"{report['required_routed_net_count']-len(report['uncovered_routed_nets'])}/"
        + f"{report['required_routed_net_count']} named routes covered"
    )
    if not report["passed"]:
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        if report["uncovered_routed_nets"]:
            print("Uncovered: " + ", ".join(report["uncovered_routed_nets"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
