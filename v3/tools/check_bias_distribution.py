#!/usr/bin/env python3
"""Validate the V3 shared-reference and balanced bias-tree manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from build_bias_distribution import ROOT, build_manifest


DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "bias_distribution.json"
DEFAULT_REPORT = ROOT / "v3" / "evidence" / "bias_distribution_check.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    reference = data["reference"]
    tree = data["bias_tree"]
    required = reference["required_extracted_device_signature"]
    lengths = [item["drawn_length_um"] for item in tree["branch_paths"].values()]
    if reference["parameters"]["aggregate_width_um"] != 64.0:
        errors.append("shared reference aggregate width changed")
    observed_offset = [
        round(reference["center_um"][axis] - reference["gencell_anchor_um"][axis], 6)
        for axis in range(2)
    ]
    if observed_offset != [5.73, 4.785]:
        errors.append(f"measured Magic PCell anchor offset changed: {observed_offset}")
    if required != {
        "count": 8,
        "model": "sky130_fd_pr__nfet_01v8",
        "diffusions": ["VGND", "vbias_ref"],
        "gate": "vbias_ref",
        "body": "VGND",
        "finger_width_um": 8.0,
        "length_um": 1.0,
    }:
        errors.append("required diode-connected extraction signature changed")
    if len(set(lengths)) != 1:
        errors.append(f"bias branch lengths differ: {lengths}")
    if set(tree["leaves"]) != {"0", "1", "2", "3"}:
        errors.append("bias tree must have exactly four named channel leaves")
    if any(item["branch_via_count"] != 0 for item in tree["branch_paths"].values()):
        errors.append("post-star channel branches must not contain unequal vias")
    if not all(
        tree[name]
        for name in ("no_length_tuning_stubs", "no_orphan_vias", "all_segment_ends_are_named_nodes_or_leaves")
    ):
        errors.append("route hygiene invariant is not asserted")
    if data["layout_policy"]["metal5_used"]:
        errors.append("project signals may not use Metal 5")
    if data["layout_policy"]["tree_max_y_um"] >= data["layout_policy"]["load_pair_keepout_starts_y_um"]:
        errors.append("bias tree intrudes into the differential-load keepout")
    if data["common_route"]["via_stack_at_root"] != ["via3", "via2"]:
        errors.append("the only post-common layer transition must remain at the named star")
    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "geometric bias-tree contract; physical DRC/LVS/precheck and extracted RC remain separate gates",
        "manifest_sha256": sha256(DEFAULT_MANIFEST),
        "reference_fingers": reference["parameters"]["fingers"],
        "bias_branch_lengths_um": lengths,
        "drawn_branch_mismatch_percent": tree["drawn_branch_mismatch_percent"],
        "post_star_branch_vias": [item["branch_via_count"] for item in tree["branch_paths"].values()],
        "tree_segment_count": len(tree["segments"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?", default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    if data != build_manifest():
        raise SystemExit("bias-distribution manifest is not reproducible from its generator")
    report = validate(data)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
