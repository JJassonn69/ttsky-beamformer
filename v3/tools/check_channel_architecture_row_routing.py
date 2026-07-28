#!/usr/bin/env python3
"""Audit the exact all-net centre-row routing pilot and bind its evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/channel_architecture_row_routing"
DEFAULT_OUTPUT = ROOT / "v3/evidence/channel_architecture_row_routing_gate.json"
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
            for token in fields[6:]
            if "=" in token
            for key, value in [token.split("=", 1)]
            if key.lower() in ("w", "l")
        }
        if set(parameters) != {"w", "l"}:
            continue
        result.append({
            "name": fields[0], "d": fields[1], "g": fields[2],
            "s": fields[3], "b": fields[4], **parameters,
        })
    return result


def diffusions(device: dict[str, object]) -> set[str]:
    return {str(device["d"]), str(device["s"])}


def audit_topology(devices: list[dict[str, object]]) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    tails = [item for item in devices if close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0)]
    gms = [item for item in devices if close(float(item["w"]), 0.84) and close(float(item["l"]), 0.6)]
    switches = [item for item in devices if close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15)]
    if (len(tails), len(gms), len(switches)) != (3, 6, 12):
        errors.append(f"device classes changed: tail={len(tails)}, gm={len(gms)}, switch={len(switches)}")
        return errors, {}
    if any(item["b"] != "VGND" for item in devices):
        errors.append("one or more MOS bodies are not tied to VGND")

    gate_counts = Counter(str(item["g"]) for item in devices)
    expected_gate_counts = {
        "vbias": 3, "sig": 3, "ref": 3,
        "g1_lop": 2, "g1_lon": 2, "g2_lop": 4, "g2_lon": 4,
    }
    if gate_counts != expected_gate_counts:
        errors.append(f"gate ownership changed: {dict(sorted(gate_counts.items()))}")

    tail_nodes: list[str] = []
    for tail in tails:
        if tail["g"] != "vbias" or "VGND" not in diffusions(tail):
            errors.append(f"{tail['name']} is not vbias-controlled between its private tail node and VGND")
            continue
        private = diffusions(tail) - {"VGND"}
        if len(private) != 1:
            errors.append(f"{tail['name']} tail node is ambiguous: {sorted(private)}")
        else:
            tail_nodes.append(next(iter(private)))
    if len(tail_nodes) != 3 or len(set(tail_nodes)) != 3:
        errors.append(f"tail nodes are not three private nodes: {tail_nodes}")

    switch_by_internal_node: dict[str, list[dict[str, object]]] = defaultdict(list)
    for switch in switches:
        for node in diffusions(switch) - {"row_outp", "row_outn", "VGND"}:
            switch_by_internal_node[node].append(switch)

    unit_records: list[dict[str, object]] = []
    used_gm_nodes: list[str] = []
    for tail_node in sorted(set(tail_nodes)):
        pair = [item for item in gms if tail_node in diffusions(item)]
        by_gate = {str(item["g"]): item for item in pair}
        if set(by_gate) != {"sig", "ref"} or len(pair) != 2:
            errors.append(f"tail {tail_node} does not own exactly one sig/ref GM pair")
            continue
        gm_nodes: dict[str, str] = {}
        for role, gm in by_gate.items():
            other = diffusions(gm) - {tail_node}
            if len(other) != 1:
                errors.append(f"tail {tail_node} {role} GM drain is ambiguous: {sorted(other)}")
            else:
                gm_nodes[role] = next(iter(other))
        if set(gm_nodes) != {"sig", "ref"}:
            continue
        used_gm_nodes.extend(gm_nodes.values())
        attached = switch_by_internal_node.get(gm_nodes["sig"], []) + switch_by_internal_node.get(gm_nodes["ref"], [])
        gates = {str(item["g"]) for item in attached}
        groups = {gate.split("_", 1)[0] for gate in gates if gate.startswith(("g1_", "g2_"))}
        if len(groups) != 1:
            errors.append(f"tail {tail_node} switches do not belong to one phase group: {sorted(gates)}")
            continue
        group = next(iter(groups))
        expected = {
            f"{group}_lop": [
                {gm_nodes["sig"], "row_outp"}, {gm_nodes["ref"], "row_outn"},
            ],
            f"{group}_lon": [
                {gm_nodes["sig"], "row_outn"}, {gm_nodes["ref"], "row_outp"},
            ],
        }
        for gate, wanted in expected.items():
            observed = [diffusions(item) for item in switches if item["g"] == gate and any(
                node in diffusions(item) for node in gm_nodes.values()
            )]
            if len(observed) != 2 or any(value not in observed for value in wanted):
                errors.append(
                    f"tail {tail_node} {gate} topology changed: "
                    f"expected {[sorted(value) for value in wanted]}, got {[sorted(value) for value in observed]}"
                )
        unit_records.append({"tail_node": tail_node, "gm_nodes": gm_nodes, "group": group})

    if len(used_gm_nodes) != 6 or len(set(used_gm_nodes)) != 6:
        errors.append("a GM drain node is shared between units")
    group_counts = Counter(str(item["group"]) for item in unit_records)
    if group_counts != {"g1": 1, "g2": 2}:
        errors.append(f"centre-row group membership changed: {dict(group_counts)}")

    expected_named = set(expected_gate_counts) | {"row_outp", "row_outn", "VGND"}
    observed_named = {
        str(device[field]) for device in devices for field in ("d", "g", "s", "b")
        if str(device[field]) in expected_named
    }
    missing = sorted(expected_named - observed_named)
    if missing:
        errors.append(f"named nets disappeared, indicating an open or label-collapsed short: {missing}")
    return errors, {
        "device_classes": {"tail": len(tails), "gm": len(gms), "switch": len(switches)},
        "gate_counts": dict(sorted(gate_counts.items())),
        "units": unit_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spice = BUILD / "v3_channel_architecture_row_routing_flat.spice"
    gds = BUILD / "v3_channel_architecture_row_routing.gds"
    marker_path = BUILD / "physical_markers.txt"
    precheck_path = BUILD / "precheck_summary.json"
    devices = parse_mos(spice)
    topology_errors, topology = audit_topology(devices)
    physical = markers(marker_path)
    expected_physical = {
        "V3_CHANNEL_ARCHITECTURE_ROW_DRC_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_ROW_EXTRACTION_FEEDBACK_COUNT": 0,
        "V3_CHANNEL_ARCHITECTURE_ROW_GDS_FEEDBACK_COUNT": 0,
    }
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    checks = {
        "magic_and_export_markers_zero": physical == expected_physical,
        "exactly_twenty_one_nmos": len(devices) == 21,
        "named_net_topology_exact": not topology_errors,
        "pinned_direct_gds_precheck_pass": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_matches_exact_gds": precheck["gds_sha256"] == sha256(gds),
    }
    sources = {
        "architecture": ROOT / "v3/layout/channel_routing_architecture.json",
        "architecture_planner": ROOT / "v3/tools/plan_channel_routing_architecture.py",
        "feasibility_matrix": ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json",
        "unit_manifest": ROOT / "v3/layout/vector_unit_placement.json",
        "unit_generator": ROOT / "v3/tools/generate_vector_unit_pilot.py",
        "row_generator": ROOT / "v3/tools/generate_channel_row_pilot.py",
        "service_row_generator": ROOT / "v3/tools/generate_channel_architecture_row_routing_pilot.py",
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact centre row with three vector units, both service corridors, all phase/output/analog/ground handoffs, named-net topology, and pinned direct-GDS geometry decks",
        "checks": checks,
        "physical_markers": physical,
        "device_count": len(devices),
        "topology": topology,
        "topology_errors": topology_errors,
        "artifacts": {
            "gds": str(gds.relative_to(ROOT)),
            "spice": str(spice.relative_to(ROOT)),
            "precheck": str(precheck_path.relative_to(ROOT)),
        },
        "gds_sha256": sha256(gds),
        "sha256": {
            "spice": sha256(spice),
            "physical_markers": sha256(marker_path),
            "precheck": sha256(precheck_path),
            **{name: sha256(path) for name, path in sources.items()},
            "checker": sha256(Path(__file__)),
        },
        "stale_evidence_policy": "promotion requires this report to be regenerated after any hashed manifest, generator, GDS, SPICE, marker, or precheck change",
        "next_gate": "promote the passing corridor/row pattern into the complete 15-unit channel and route the balanced G4/G8 trees against the same reserved tracks",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
