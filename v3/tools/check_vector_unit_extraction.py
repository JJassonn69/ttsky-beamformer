#!/usr/bin/env python3
"""Audit the exact extracted topology of the routed V3 vector-unit pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "vector_unit_pilot"


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
            "name": fields[0],
            "d": fields[1],
            "g": fields[2],
            "s": fields[3],
            "b": fields[4],
            **parameters,
        })
    return result


def diffusion_set(device: dict[str, object]) -> set[str]:
    return {str(device["d"]), str(device["s"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spice", type=Path, default=BUILD / "v3_vector_unit_pilot_flat.spice")
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_vector_unit_pilot.gds")
    parser.add_argument("--log", type=Path, default=BUILD / "magic_extract.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3" / "layout" / "vector_unit_placement.json")
    parser.add_argument("--output", type=Path, default=BUILD / "topology_audit.json")
    args = parser.parse_args()

    devices = parse_mos(args.spice)
    log = args.log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed = re.compile(r'^Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.$')
    unexpected = [line for line in warnings if not allowed.fullmatch(line)]

    tails = [item for item in devices if close(float(item["w"]), 5.07) and close(float(item["l"]), 1.0)]
    gms = [item for item in devices if close(float(item["w"]), 0.84) and close(float(item["l"]), 0.6)]
    switches = [item for item in devices if close(float(item["w"]), 0.65) and close(float(item["l"]), 0.15)]
    topology_errors: list[str] = []
    if len(tails) != 1 or len(gms) != 2 or len(switches) != 4:
        topology_errors.append(
            f"unexpected device classes: tail={len(tails)}, gm={len(gms)}, switch={len(switches)}"
        )
    if any(item["b"] != "VGND" for item in devices):
        topology_errors.append("not every MOS body is tied to VGND")

    inferred: dict[str, object] = {}
    if not topology_errors:
        tail = tails[0]
        if tail["g"] != "vbias" or "VGND" not in diffusion_set(tail):
            topology_errors.append("tail device is not vbias-controlled between tail and VGND")
        else:
            tail_node = next(iter(diffusion_set(tail) - {"VGND"}))
            gm_by_gate = {str(item["g"]): item for item in gms}
            if set(gm_by_gate) != {"sig", "ref"}:
                topology_errors.append(f"GM gate ownership changed: {sorted(gm_by_gate)}")
            else:
                gm_nodes: dict[str, str] = {}
                for gate, item in gm_by_gate.items():
                    if tail_node not in diffusion_set(item):
                        topology_errors.append(f"{gate} GM device does not share the tail node")
                        continue
                    other = diffusion_set(item) - {tail_node}
                    if len(other) != 1:
                        topology_errors.append(f"{gate} GM drain node is ambiguous: {sorted(other)}")
                    else:
                        gm_nodes[gate] = next(iter(other))
                expected = {
                    "lop_left": {"outp", gm_nodes.get("sig", "<missing>")},
                    "lon_left": {"outn", gm_nodes.get("sig", "<missing>")},
                    "lon_right": {"outp", gm_nodes.get("ref", "<missing>")},
                    "lop_right": {"outn", gm_nodes.get("ref", "<missing>")},
                }
                switch_by_gate = {str(item["g"]): item for item in switches}
                if set(switch_by_gate) != set(expected):
                    topology_errors.append(f"switch gate ownership changed: {sorted(switch_by_gate)}")
                else:
                    for gate, wanted in expected.items():
                        observed = diffusion_set(switch_by_gate[gate])
                        if observed != wanted:
                            topology_errors.append(
                                f"{gate} switch diffusion mismatch: expected {sorted(wanted)}, got {sorted(observed)}"
                            )
                inferred = {"tail_node": tail_node, "gm_nodes": gm_nodes}

    checks = {
        "magic_drc_zero": marker(log, "V3_VECTOR_UNIT_DRC_COUNT") == 0,
        "magic_extraction_feedback_zero": marker(log, "V3_VECTOR_UNIT_EXTRACTION_FEEDBACK_COUNT") == 0,
        "magic_gds_feedback_zero": marker(log, "V3_VECTOR_UNIT_GDS_FEEDBACK_COUNT") == 0,
        "only_classified_magic_warnings": not unexpected,
        "exactly_seven_nmos": len(devices) == 7,
        "device_classes_match": len(tails) == 1 and len(gms) == 2 and len(switches) == 4,
        "bodies_grounded": all(item["b"] == "VGND" for item in devices),
        "vector_unit_topology_exact": not topology_errors,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact seven-transistor V3 vector-unit pilot topology and direct-GDS geometry",
        "checks": checks,
        "topology_errors": topology_errors,
        "unexpected_magic_warnings": unexpected,
        "device_count": len(devices),
        "devices": devices,
        "inferred_internal_nodes": inferred,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "sha256": {
            "spice": sha256(args.spice),
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "manifest": sha256(args.manifest),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
