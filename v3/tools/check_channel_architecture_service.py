#!/usr/bin/env python3
"""Audit the exact 15-unit service-corridor skeleton and bind its evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_architecture_service"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_architecture_service_gate.json"
MODEL = "sky130_fd_pr__nfet_01v8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-9)


def markers(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            result[key] = int(value)
    return result


def parse_mos(path: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.split()
        if len(fields) < 10 or not fields[0].upper().startswith("X") or fields[5] != MODEL:
            continue
        parameters = {
            key.lower(): float(value)
            for token in fields[6:] if "=" in token
            for key, value in [token.split("=", 1)]
            if key.lower() in ("w", "l")
        }
        if set(parameters) == {"w", "l"}:
            result.append({
                "name": fields[0], "d": fields[1], "g": fields[2],
                "s": fields[3], "b": fields[4], **parameters,
            })
    return result


def diffusions(device: dict[str, object]) -> set[str]:
    return {str(device["d"]), str(device["s"])}


def audit(devices: list[dict[str, object]]) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    tails = [item for item in devices if close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0)]
    gms = [item for item in devices if close(float(item["w"]), 0.84) and close(float(item["l"]), 0.6)]
    switches = [item for item in devices if close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15)]
    if (len(tails), len(gms), len(switches)) != (15, 30, 60):
        return [f"device classes changed: tail={len(tails)}, gm={len(gms)}, switch={len(switches)}"], {}
    if any(item["b"] != "VGND" for item in devices):
        errors.append("one or more MOS bodies are not tied to VGND")
    if Counter(str(item["g"]) for item in tails) != {"vbias": 15}:
        errors.append("tail-gate ownership is not fifteen shared vbias gates")
    if Counter(str(item["g"]) for item in gms) != {"sig": 15, "ref": 15}:
        errors.append("GM-gate ownership is not fifteen shared sig/ref pairs")

    expected_prefixes = {f"u{index:02d}" for index in range(15)}
    switch_prefix_counts: Counter[str] = Counter()
    for switch in switches:
        match = re.fullmatch(r"(u\d{2})_(lop|lon)", str(switch["g"]))
        if not match:
            errors.append(f"{switch['name']} has unexpected local phase gate {switch['g']}")
        else:
            switch_prefix_counts[match.group(1)] += 1
    if set(switch_prefix_counts) != expected_prefixes or any(
        switch_prefix_counts[prefix] != 4 for prefix in expected_prefixes
    ):
        errors.append(f"local phase gate populations changed: {dict(sorted(switch_prefix_counts.items()))}")

    tail_nodes: list[str] = []
    for tail in tails:
        private = diffusions(tail) - {"VGND"}
        if "VGND" not in diffusions(tail) or len(private) != 1:
            errors.append(f"{tail['name']} is not between one private node and VGND")
        else:
            tail_nodes.append(next(iter(private)))
    gm_private_nodes: list[str] = []
    unit_records: list[dict[str, object]] = []
    for tail_node in sorted(set(tail_nodes)):
        pair = [item for item in gms if tail_node in diffusions(item)]
        by_gate = {str(item["g"]): item for item in pair}
        if len(pair) != 2 or set(by_gate) != {"sig", "ref"}:
            errors.append(f"tail {tail_node} does not own one sig/ref GM pair")
            continue
        gm_nodes = {
            role: next(iter(diffusions(item) - {tail_node}))
            for role, item in by_gate.items()
            if len(diffusions(item) - {tail_node}) == 1
        }
        if set(gm_nodes) != {"sig", "ref"}:
            errors.append(f"tail {tail_node} has ambiguous GM drain nodes")
            continue
        gm_private_nodes.extend(gm_nodes.values())
        attached = [
            item for item in switches
            if any(node in diffusions(item) for node in gm_nodes.values())
        ]
        prefixes = {
            str(item["g"]).split("_", 1)[0]
            for item in attached if re.fullmatch(r"u\d{2}_(?:lop|lon)", str(item["g"]))
        }
        if len(prefixes) != 1:
            errors.append(f"tail {tail_node} switches span unit prefixes {sorted(prefixes)}")
            continue
        prefix = next(iter(prefixes))
        expected = {
            f"{prefix}_lop": [
                {gm_nodes["sig"], "row_outp"}, {gm_nodes["ref"], "row_outn"},
            ],
            f"{prefix}_lon": [
                {gm_nodes["sig"], "row_outn"}, {gm_nodes["ref"], "row_outp"},
            ],
        }
        for gate, wanted in expected.items():
            observed = [diffusions(item) for item in attached if item["g"] == gate]
            if len(observed) != 2 or any(value not in observed for value in wanted):
                errors.append(
                    f"{prefix} {gate} topology changed: expected "
                    f"{[sorted(value) for value in wanted]}, got {[sorted(value) for value in observed]}"
                )
        unit_records.append({"prefix": prefix, "tail_node": tail_node, "gm_nodes": gm_nodes})

    if len(tail_nodes) != 15 or len(set(tail_nodes)) != 15:
        errors.append("tail nodes are not fifteen private nodes")
    if len(gm_private_nodes) != 30 or len(set(gm_private_nodes)) != 30:
        errors.append("a GM drain node is shared between units")
    if {str(item["prefix"]) for item in unit_records} != expected_prefixes:
        errors.append("not every unit prefix owns one complete analog cell")
    named = {str(item[field]) for item in devices for field in ("d", "g", "s", "b")}
    missing = sorted({"sig", "ref", "vbias", "row_outp", "row_outn", "VGND"} - named)
    if missing:
        errors.append(f"global service nets disappeared: {missing}")
    return errors, {
        "device_classes": {"tail": len(tails), "gm": len(gms), "switch": len(switches)},
        "unit_count": len(unit_records),
        "local_phase_gate_counts": dict(sorted(switch_prefix_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spice = BUILD / "v3_channel_architecture_service_flat.spice"
    gds = BUILD / "v3_channel_architecture_service.gds"
    marker_path = BUILD / "physical_markers.txt"
    precheck_path = BUILD / "precheck_summary.json"
    devices = parse_mos(spice)
    topology_errors, topology = audit(devices)
    physical = markers(marker_path)
    expected_physical = {
        "V3_CHANNEL_ARCHITECTURE_SERVICE_DRC_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_SERVICE_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_SERVICE_GDS_FEEDBACK_COUNT": 0,
    }
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    matrix = json.loads((ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json").read_text(encoding="utf-8"))
    group_counts = Counter(str(item["group_weight"]) for item in matrix["matrix"]["instances"])
    checks = {
        "magic_and_export_markers_zero": physical == expected_physical,
        "exactly_one_hundred_five_nmos": len(devices) == 105,
        "all_fifteen_service_topologies_exact": not topology_errors,
        "binary_group_population_exact": group_counts == {"1": 1, "2": 2, "4": 4, "8": 8},
        "pinned_direct_gds_precheck_pass": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(gds),
    }
    sources = {
        "architecture": ROOT / "v3/layout/channel_routing_architecture.json",
        "architecture_planner": ROOT / "v3/tools/plan_channel_routing_architecture.py",
        "matrix": ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json",
        "unit_manifest": ROOT / "v3/layout/vector_unit_placement.json",
        "matrix_generator": ROOT / "v3/tools/generate_channel_matrix_pilot.py",
        "service_generator": ROOT / "v3/tools/generate_channel_architecture_service_pilot.py",
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "complete exact 15-unit channel with elevated row grounds, shared sig/ref/vbias spines, differential output spines, local LO merges, and pinned direct-GDS decks; global group phase trees absent",
        "checks": checks,
        "physical_markers": physical,
        "device_count": len(devices),
        "group_counts": dict(sorted(group_counts.items())),
        "topology": topology,
        "topology_errors": topology_errors,
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": sha256(gds),
        "sha256": {
            "spice": sha256(spice),
            "physical_markers": sha256(marker_path),
            "precheck": sha256(precheck_path),
            **{name: sha256(path) for name, path in sources.items()},
            "checker": sha256(Path(__file__)),
        },
        "stale_evidence_policy": "promotion requires regeneration after any hashed source or physical artifact changes",
        "next_gate": "route all eight group phase nets against this exact service-skeleton GDS obstacle map",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
