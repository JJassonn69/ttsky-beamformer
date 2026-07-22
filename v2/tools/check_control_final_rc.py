#!/usr/bin/env python3
"""Audit zero-pruning distributed RC across all V2 control and analog routes."""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.tools.check_control_service_rc import equivalence_alias_coverage
from v2.tools.check_support_rc import required_routed_nets as required_analog_nets
from tools.check_distributed_rc import annotation_counts, rc_details, spice_elements
from v2.tools.check_magic_rc_log import FATAL_PATTERNS


MINIMUM_RESISTOR_EMISSION_RATIO = 0.90
OUTPUT_PAD_INTERNAL_COORDINATES = {
    "sum_p": (14996, 100),  # ua[4] at 74.98 um, 0.50 um
    "sum_n": (11132, 100),  # ua[5] at 55.66 um, 0.50 um
}
KNOWN_MAGIC_WARNING_PATTERNS = (
    re.compile(r"^Warning:\s+Calma reading is not undoable!\s+I hope that's OK\.$"),
    re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$'),
    re.compile(r"^Warning:\s+viali at \d+ \d+ smaller than extract section allows$"),
)


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_pad_rc_endpoints(
    res_ext_path: Path, aliases: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Prove that each physical output pad survives as an RC mesh endpoint."""
    rnode_re = re.compile(
        r'^rnode "([^"]+)"\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\S+$'
    )
    coordinates: dict[str, tuple[int, int]] = {}
    for line in res_ext_path.read_text(errors="replace").splitlines():
        match = rnode_re.match(line)
        if match:
            coordinates[match.group(1)] = (int(match.group(2)), int(match.group(3)))

    result: dict[str, dict[str, Any]] = {}
    for net, expected in OUTPUT_PAD_INTERNAL_COORDINATES.items():
        alias = aliases.get(net, {}).get("resistor_graph_alias", net)
        candidates = {
            name: point for name, point in coordinates.items()
            if name == alias or name.startswith(alias + ".")
        }
        matches = sorted(name for name, point in candidates.items() if point == expected)
        result[net] = {
            "expected_internal_coordinate": list(expected),
            "resistor_graph_alias": alias,
            "matched_rnode": matches[0] if matches else None,
            "matched": bool(matches),
        }
    return result


def audit(
    base_path: Path,
    rc_path: Path,
    res_ext_path: Path,
    geometry: dict[str, Any],
    log: str,
) -> dict[str, Any]:
    base = spice_elements(base_path)
    rc = spice_elements(rc_path)
    control_labels = set(geometry["label_net_map"])
    analog = required_analog_nets(include_output_pads=True)
    required = control_labels | analog | {"VDPWR", "VGND"}
    details = rc_details(rc, required)
    rnodes, annotated = annotation_counts(res_ext_path)
    emitted_ratio = details["resistors"] / annotated if annotated else 0.0
    top_ext = res_ext_path.with_name(
        res_ext_path.name.removesuffix(".res.ext") + ".ext"
    )
    aliases = equivalence_alias_coverage(
        top_ext, rc, details["uncovered_manifest_nets"]
    ) if top_ext.is_file() else {}
    output_endpoints = output_pad_rc_endpoints(res_ext_path, aliases)
    uncovered = sorted(set(details["uncovered_manifest_nets"]) - set(aliases))
    fatal = {
        name: pattern.search(log).group(0)
        for name, pattern in FATAL_PATTERNS.items() if pattern.search(log)
    }
    warning_lines = [
        line.strip() for line in log.splitlines()
        if line.lstrip().startswith("Warning:")
    ]
    unexpected_warnings = [
        line for line in warning_lines
        if not any(pattern.fullmatch(line) for pattern in KNOWN_MAGIC_WARNING_PATTERNS)
    ]
    viali_mesh_warnings = [
        line for line in warning_lines if "viali at" in line
    ]
    outputs = all(
        re.search(rf"^{name}=\S+\s*$", log, flags=re.MULTILINE)
        for name in (
            "CONTROL_FINAL_BASE_SPICE", "CONTROL_FINAL_RC_SPICE",
            "CONTROL_FINAL_RES_EXT",
        )
    )
    checks = {
        "all_206_router_labels_present": len(control_labels) == 206,
        "magic_drc_clean": marker(log, "CONTROL_FINAL_RC_DRC_COUNT") == 0,
        "magic_feedback_clean": marker(
            log, "CONTROL_FINAL_RC_EXTRACTION_FEEDBACK_COUNT"
        ) == 0,
        "magic_outputs_complete": log.count("exttospice finished.") >= 2 and outputs,
        "no_silent_magic_failures": not fatal,
        "only_classified_magic_warnings": (
            not unexpected_warnings and len(viali_mesh_warnings) <= 1
        ),
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
        "output_pad_branches_preserved_in_resistor_mesh": all(
            item["matched"] for item in output_endpoints.values()
        ),
        "internal_resistor_nodes_emitted": details["internal_resistor_nodes"] >= len(required),
        "resistor_records_well_formed": not details["malformed_resistors"],
        "resistor_values_positive": not details["nonpositive_resistors"],
        "no_extraction_attribute_nodes": not details["attribute_like_resistor_nodes"],
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "required_control_route_count": len(control_labels),
        "required_analog_route_count": len(analog),
        "required_routed_net_count": len(required),
        "covered_routed_net_count": len(required) - len(uncovered),
        "uncovered_routed_nets": uncovered,
        "equivalence_alias_coverage": aliases,
        "output_pad_rc_endpoints": output_endpoints,
        "base": {
            "resistors": len(base["R"]), "capacitors": len(base["C"]),
            "devices": len(base["X"]),
        },
        "distributed_rc": details,
        "annotation": {
            "rnodes": rnodes, "resistors": annotated,
            "spice_to_annotation_ratio": emitted_ratio,
            "minimum_spice_to_annotation_ratio": MINIMUM_RESISTOR_EMISSION_RATIO,
        },
        "magic_fatal_matches": fatal,
        "magic_warnings": {
            "all": warning_lines,
            "unexpected": unexpected_warnings,
            "viali_extresist_mesh_fallback_count": len(viali_mesh_warnings),
            "viali_note": (
                "Magic extresist emits one contact node when a legal viali "
                "is smaller than its CIF contact-array meshing section; exact "
                "GDS cut dimensions and physical DRC are checked separately."
            ),
        },
        "sha256": {
            "base": sha256(base_path), "distributed_rc": sha256(rc_path),
            "resistance_annotation": sha256(res_ext_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    work = Path("build/v2/control_routing/final_rc")
    parser.add_argument("--base", type=Path, default=work / "control_final_base.spice")
    parser.add_argument("--rc", type=Path, default=work / "control_final_rc.spice")
    parser.add_argument(
        "--res-ext", type=Path,
        default=work / "v2_control_final_rc_flat.res.ext",
    )
    parser.add_argument(
        "--geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    parser.add_argument("--log", type=Path, default=work / "magic_rc.log")
    parser.add_argument("--report", type=Path, default=work / "coverage_audit.json")
    args = parser.parse_args()
    report = audit(
        args.base, args.rc, args.res_ext,
        json.loads(args.geometry.read_text()), args.log.read_text(errors="replace"),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    details = report["distributed_rc"]
    print(
        "Complete V2 distributed-RC "
        + ("passed" if report["status"] == "pass" else "FAILED")
        + f": {details['resistors']} resistors, {details['capacitors']} capacitors, "
        + f"{report['covered_routed_net_count']}/{report['required_routed_net_count']} "
        + "named routes covered"
    )
    if report["status"] != "pass":
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        if report["uncovered_routed_nets"]:
            print("Uncovered: " + ", ".join(report["uncovered_routed_nets"]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
