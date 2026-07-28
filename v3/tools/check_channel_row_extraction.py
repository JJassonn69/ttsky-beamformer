#!/usr/bin/env python3
"""Audit topology and physical evidence for the exact three-unit V3 row pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_row_pilot"
DEFAULT_OUTPUT = ROOT / "v3" / "evidence" / "channel_row_physical_gate.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(log: str, name: str) -> int | None:
    values = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(values[-1]) if values else None


def close(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-9)


def parse_mos(path: Path) -> list[dict[str, object]]:
    result = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.split()
        if not fields or not fields[0].upper().startswith("X") or len(fields) < 10:
            continue
        parameters = {
            key.lower(): float(value)
            for token in fields[6:]
            if "=" in token
            for key, value in [token.split("=", 1)]
            if key.lower() in ("w", "l")
        }
        if fields[5] != "sky130_fd_pr__nfet_01v8" or set(parameters) != {"w", "l"}:
            continue
        result.append({
            "name": fields[0], "d": fields[1], "g": fields[2],
            "s": fields[3], "b": fields[4], **parameters,
        })
    return result


def diffusion_set(device: dict[str, object]) -> set[str]:
    return {str(device["d"]), str(device["s"])}


def audit_unit(prefix: str, devices: list[dict[str, object]]) -> tuple[list[str], dict[str, object]]:
    errors = []
    tails = [item for item in devices if close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0)]
    gms = [item for item in devices if close(float(item["w"]), 0.84) and close(float(item["l"]), 0.6)]
    switches = [item for item in devices if close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15)]
    if len(tails) != 1 or len(gms) != 2 or len(switches) != 4:
        return [f"{prefix} device classes changed: tail={len(tails)}, gm={len(gms)}, switch={len(switches)}"], {}
    if any(item["b"] != "VGND" for item in devices):
        errors.append(f"{prefix} has a MOS body not tied to VGND")

    tail = tails[0]
    if tail["g"] != f"{prefix}_vbias" or "VGND" not in diffusion_set(tail):
        errors.append(f"{prefix} tail is not vbias-controlled between tail and VGND")
        return errors, {}
    tail_nodes = diffusion_set(tail) - {"VGND"}
    if len(tail_nodes) != 1:
        errors.append(f"{prefix} tail node is ambiguous: {sorted(tail_nodes)}")
        return errors, {}
    tail_node = next(iter(tail_nodes))

    gm_by_gate = {str(item["g"]): item for item in gms}
    wanted_gates = {f"{prefix}_sig", f"{prefix}_ref"}
    if set(gm_by_gate) != wanted_gates:
        errors.append(f"{prefix} GM gates changed: {sorted(gm_by_gate)}")
        return errors, {"tail_node": tail_node}
    gm_nodes = {}
    for role in ("sig", "ref"):
        item = gm_by_gate[f"{prefix}_{role}"]
        if tail_node not in diffusion_set(item):
            errors.append(f"{prefix} {role} GM does not share the tail node")
            continue
        other = diffusion_set(item) - {tail_node}
        if len(other) != 1:
            errors.append(f"{prefix} {role} GM drain is ambiguous: {sorted(other)}")
        else:
            gm_nodes[role] = next(iter(other))

    expected = {
        "lop": [
            {f"{prefix}_outp", gm_nodes.get("sig", "<missing>")},
            {f"{prefix}_outn", gm_nodes.get("ref", "<missing>")},
        ],
        "lon": [
            {f"{prefix}_outn", gm_nodes.get("sig", "<missing>")},
            {f"{prefix}_outp", gm_nodes.get("ref", "<missing>")},
        ],
    }
    switch_by_gate: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in switches:
        switch_by_gate[str(item["g"])].append(item)
    for role in ("lop", "lon"):
        gate = f"{prefix}_{role}"
        observed = [diffusion_set(item) for item in switch_by_gate.get(gate, [])]
        wanted = expected[role]
        if len(observed) != 2 or any(value not in observed for value in wanted):
            errors.append(
                f"{prefix} {role} switch topology changed: expected "
                f"{[sorted(value) for value in wanted]}, got {[sorted(value) for value in observed]}"
            )
    if set(switch_by_gate) != {f"{prefix}_lop", f"{prefix}_lon"}:
        errors.append(f"{prefix} switch gate ownership changed: {sorted(switch_by_gate)}")
    return errors, {"tail_node": tail_node, "gm_nodes": gm_nodes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=BUILD / "v3_channel_row_pilot_flat.spice")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_channel_row_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "magic_extract.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--matrix", type=Path, default=ROOT / "v3" / "layout" / "channel_matrix_placement.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    devices = parse_mos(args.spice)
    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]

    by_prefix: dict[str, list[dict[str, object]]] = defaultdict(list)
    unowned = []
    for device in devices:
        gate = str(device["g"])
        match = re.match(r"^(u[0-2])_", gate)
        if match:
            by_prefix[match.group(1)].append(device)
        else:
            unowned.append(device["name"])
    topology_errors = []
    inferred = {}
    for prefix in ("u0", "u1", "u2"):
        errors, nodes = audit_unit(prefix, by_prefix[prefix])
        topology_errors.extend(errors)
        inferred[prefix] = nodes
    if unowned:
        topology_errors.append(f"devices without a unit-owned gate: {unowned}")

    private_nodes = []
    for nodes in inferred.values():
        if "tail_node" in nodes:
            private_nodes.append(nodes["tail_node"])
        private_nodes.extend(nodes.get("gm_nodes", {}).values())
    if len(private_nodes) != len(set(private_nodes)):
        topology_errors.append("an internal tail/GM node is shared between units")

    checks = {
        "magic_drc_zero": marker(log, "V3_CHANNEL_ROW_DRC_COUNT") == 0,
        "magic_extraction_feedback_zero": marker(log, "V3_CHANNEL_ROW_EXTRACTION_FEEDBACK_COUNT") == 0,
        "magic_gds_feedback_zero": marker(log, "V3_CHANNEL_ROW_GDS_FEEDBACK_COUNT") == 0,
        "only_classified_magic_warnings": not unexpected,
        "exactly_twenty_one_nmos": len(devices) == 21,
        "exactly_three_seven_device_units": set(by_prefix) == {"u0", "u1", "u2"} and all(
            len(by_prefix[prefix]) == 7 for prefix in ("u0", "u1", "u2")
        ),
        "row_topology_exact": not topology_errors,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact three-unit centre-row pilot: R0/MY abutment, local LON/LOP merges, shared substrate, topology, and direct-GDS geometry",
        "checks": checks,
        "topology_errors": topology_errors,
        "unexpected_magic_warnings": unexpected,
        "device_count": len(devices),
        "device_counts_by_unit": {prefix: len(items) for prefix, items in sorted(by_prefix.items())},
        "inferred_internal_nodes": inferred,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "sha256": {
            "spice": sha256(args.spice),
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "matrix_manifest": sha256(args.matrix),
            "generator": sha256(ROOT / "v3" / "tools" / "generate_channel_row_pilot.py"),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "allocate and close balanced 1/2/4/8 group H-trees before full 15-unit replication",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
