#!/usr/bin/env python3
"""Consolidate the exact-submission geometry regression into tracked evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FINAL_GDS = ROOT / "gds/tt_um_jjassonn69_beamformer.gds"
WORK = ROOT / "build/v2/submission/final_regression"
NONLINEAR_MODEL = ROOT / "v2/spice/sky130_fd_pr__cap_var_lvt.model.spice"
LINEAR_MODEL = ROOT / "v2/spice/sky130_fd_pr__cap_var_lvt.linearized_1p2v.spice"
OUTPUT = ROOT / "v2/evidence/submission_geometry_regression.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def elements(path: Path) -> dict[str, int]:
    counts = {"devices": 0, "capacitors": 0, "resistors": 0}
    positive_resistors = True
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in "*.+;":
            continue
        if line[0].upper() == "X":
            counts["devices"] += 1
        elif line[0].upper() == "C":
            counts["capacitors"] += 1
        elif line[0].upper() == "R":
            counts["resistors"] += 1
            fields = line.split()
            try:
                positive_resistors &= len(fields) >= 4 and float(fields[3]) > 0
            except ValueError:
                positive_resistors = False
    counts["all_resistors_positive"] = int(positive_resistors)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-netlist", type=Path, default=WORK / "control_final_base_normalized.spice")
    parser.add_argument("--rc-netlist", type=Path, default=WORK / "control_final_rc_normalized.spice")
    parser.add_argument("--extraction-log", type=Path, default=WORK / "extraction.log")
    parser.add_argument("--base-codebook", type=Path, default=WORK / "base_codebook_summary.json")
    parser.add_argument("--rc-nominal", type=Path, default=WORK / "rc_nominal_report.json")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    required = (
        FINAL_GDS, args.base_netlist, args.rc_netlist, args.extraction_log,
        args.base_codebook, args.rc_nominal, NONLINEAR_MODEL, LINEAR_MODEL,
    )
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing regression input: {path}")

    gds_hash = sha256(FINAL_GDS)
    base_hash = sha256(args.base_netlist)
    rc_hash = sha256(args.rc_netlist)
    nonlinear_hash = sha256(NONLINEAR_MODEL)
    linear_hash = sha256(LINEAR_MODEL)
    base_counts = elements(args.base_netlist)
    rc_counts = elements(args.rc_netlist)
    extraction_log = args.extraction_log.read_text(encoding="utf-8", errors="replace")
    codebook = json.loads(args.base_codebook.read_text(encoding="utf-8"))
    rc_nominal = json.loads(args.rc_nominal.read_text(encoding="utf-8"))

    errors: list[str] = []
    for marker in (
        "CONTROL_FINAL_RC_DRC_COUNT=0",
        "CONTROL_FINAL_RC_EXTRACTION_FEEDBACK_COUNT=0",
    ):
        if marker not in extraction_log:
            errors.append(f"missing extraction marker: {marker}")
    if extraction_log.count("exttospice finished.") < 2:
        errors.append("both base and distributed-RC ext2spice completions are required")
    if base_counts["resistors"] != 0:
        errors.append("base reference unexpectedly contains distributed resistors")
    if rc_counts["resistors"] <= 0 or not rc_counts["all_resistors_positive"]:
        errors.append("distributed-RC resistor graph is absent or malformed")
    if base_counts["devices"] != rc_counts["devices"] or base_counts["devices"] == 0:
        errors.append("base/RC device counts differ")

    codebook_hashes = codebook.get("metrics", {}).get("artifact_hashes", {})
    if codebook.get("status") != "pass" or codebook.get("case_count") != 20:
        errors.append("exact-final base codebook is not a passing 20-case matrix")
    if codebook_hashes.get("gds_sha256") != [gds_hash]:
        errors.append("base codebook GDS hash differs")
    if codebook_hashes.get("netlist_sha256") != [base_hash]:
        errors.append("base codebook netlist hash differs")
    if codebook_hashes.get("extracted_varactor_model_sha256") != [nonlinear_hash]:
        errors.append("base codebook nonlinear-varactor model hash differs")

    if rc_nominal.get("status") != "pass" or rc_nominal.get("timed_out"):
        errors.append("exact-final distributed-RC nominal case did not pass")
    if rc_nominal.get("gds_sha256") != gds_hash:
        errors.append("RC nominal GDS hash differs")
    if rc_nominal.get("netlist_sha256") != rc_hash:
        errors.append("RC nominal netlist hash differs")
    if rc_nominal.get("extracted_varactor_model_sha256") != linear_hash:
        errors.append("RC nominal linearized-varactor model hash differs")

    diagonal = codebook.get("metrics", {}).get("constructive_diagonal_v_rms", [])
    if len(diagonal) != 4 or min(diagonal, default=0.0) <= 0:
        errors.append("base codebook constructive diagonal is incomplete")
        base_constructive = 0.0
    else:
        base_constructive = float(diagonal[0])
    rc_analysis = rc_nominal.get("analysis", {})
    rc_constructive = float(rc_analysis.get("output_tone_rms_v", 0.0))
    loss_db = (
        20.0 * math.log10(base_constructive / rc_constructive)
        if base_constructive > 0 and rc_constructive > 0 else math.inf
    )
    if loss_db >= 1.0:
        errors.append(f"base-to-RC nominal loss is {loss_db:.3f} dB")
    if not 1.1 < float(rc_analysis.get("vcm_v", 0.0)) < 1.3:
        errors.append("RC nominal VCM is outside 1.1..1.3 V")
    if not 0.8 < float(rc_analysis.get("output_common_mode_v", 0.0)) < 1.2:
        errors.append("RC nominal output common mode is outside 0.8..1.2 V")
    if float(rc_analysis.get("minimum_time_aligned_gm_drain_to_tail_v", 0.0)) <= 0:
        errors.append("RC nominal active-device headroom is nonpositive")
    maximum_phase_skew_s = max(
        (float(item["skew_s"]) for item in rc_analysis.get("phase_leaf_skew", [])),
        default=math.inf,
    )
    if maximum_phase_skew_s >= 10e-12:
        errors.append("RC phase-tree skew exceeds 10 ps")

    report = {
        "schema_version": 1,
        "as_of": "2026-07-25",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": (
            "targeted geometry-sensitive regression after topology-preserving "
            "official-precheck repair; device mismatch and broad PVT evidence "
            "remain bound to the electrically equivalent frozen candidate"
        ),
        "submission_gds": artifact(FINAL_GDS),
        "extraction": {
            "log": artifact(args.extraction_log),
            "base_netlist": artifact(args.base_netlist),
            "distributed_rc_netlist": artifact(args.rc_netlist),
            "base_counts": base_counts,
            "distributed_rc_counts": rc_counts,
            "magic_drc_count": 0,
            "extraction_feedback_count": 0,
        },
        "models": {
            "nonlinear_varactor": artifact(NONLINEAR_MODEL),
            "linearized_varactor_1p2v": artifact(LINEAR_MODEL),
            "linearization_scope": (
                "distributed-RC convergence only; 2.604860136 pF and "
                "1097.313346 ohm per physical varactor at VCM=1.2 V"
            ),
        },
        "base_codebook": {
            "report": artifact(args.base_codebook),
            "case_count": codebook.get("case_count"),
            "minimum_rejection_db": codebook.get("metrics", {}).get("minimum_rejection_db"),
            "constructive_spread_db": codebook.get("metrics", {}).get("constructive_spread_db"),
            "constructive_diagonal_v_rms": diagonal,
        },
        "distributed_rc_nominal": {
            "report": artifact(args.rc_nominal),
            "output_tone_rms_v": rc_constructive,
            "base_to_rc_loss_db": loss_db,
            "vcm_v": rc_analysis.get("vcm_v"),
            "output_common_mode_v": rc_analysis.get("output_common_mode_v"),
            "minimum_headroom_v": rc_analysis.get("minimum_time_aligned_gm_drain_to_tail_v"),
            "maximum_phase_tree_skew_s": maximum_phase_skew_s,
        },
        "rerun_policy": {
            "repeated": [
                "official physical precheck", "Magic DRC", "extracted topology",
                "exact-final base 20-case codebook", "exact-final distributed-RC nominal",
            ],
            "not_repeated": [
                "60-seed device mismatch", "full trim calibration", "broad PVT matrix",
            ],
            "reason": (
                "transistor/passive instances and normalized extracted topology are "
                "unchanged; those campaigns test device statistics and architecture, "
                "not the repaired wire geometry"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
