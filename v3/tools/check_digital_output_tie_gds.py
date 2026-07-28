#!/usr/bin/env python3
"""Prove the 24 TinyTapeout digital outputs are physically tied only to VGND."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONNECT_RE = re.compile(r'^(?:merge|equiv) "([^"]+)" "([^"]+)"')
MAGIC_METRICS = {
    "gds_feedback": re.compile(r"V3_OUTPUT_TIE_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_OUTPUT_TIE_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(r"V3_OUTPUT_TIE_EXTRACTION_FEEDBACK_COUNT=(\d+)"),
    "feedback_after_clear": re.compile(r"V3_OUTPUT_TIE_FEEDBACK_AFTER_CLEAR=(\d+)"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def root(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.root(self.parent[item])
        return self.parent[item]

    def union(self, first: str, second: str) -> None:
        left, right = self.root(first), self.root(second)
        if left != right:
            self.parent[right] = left


def add_connections(union: UnionFind, path: Path, prefix: str = "") -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = CONNECT_RE.match(line)
        if not match:
            continue
        first, second = match.groups()
        first = f"{prefix}{first}" if prefix else first
        second = f"{prefix}{second}" if prefix else second
        union.union(first, second)
        names.update((first, second))
    return names


def spice_population(path: Path) -> tuple[int, Counter[str], Counter[str]]:
    count = 0
    models: Counter[str] = Counter()
    terminals: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("X"):
            continue
        tokens = line.split()
        model_index = next(
            index for index, token in enumerate(tokens)
            if token.startswith("sky130_fd_pr__")
        )
        count += 1
        models[tokens[model_index]] += 1
        terminals.update(tokens[1:model_index])
    return count, models, terminals


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    assembly = json.loads(args.assembly.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    source_gate = json.loads(args.source_gate.read_text(encoding="utf-8"))

    source = plan["source_checkpoint"]
    if source_gate.get("status") != "pass" or source_gate.get("gds_sha256") != source["sha256"]:
        errors.append("source analog-input gate is not closed on the planned GDS")
    if sha256(args.source_gds) != source["sha256"]:
        errors.append("source GDS differs from the tie-low contract")
    if geometry.get("status") != "generated from hash-locked physical tie-low plan":
        errors.append("tie-low geometry provenance is not closed")
    if assembly.get("status") != "pass" or assembly.get("output_sha256") != sha256(args.gds):
        errors.append("assembly report does not bind the GDS under audit")
    if assembly.get("geometry_sha256") != sha256(args.geometry):
        errors.append("assembly report does not bind the tie geometry")
    if precheck.get("gds_sha256") != sha256(args.gds):
        errors.append("direct-GDS precheck refers to another GDS")
    if precheck.get("status") != "pass" or any(
        item["markers"] != 0 for item in precheck["checks"].values()
    ):
        errors.append("direct-GDS precheck is not clean")

    expected_outputs = [
        f"V3O{index:03d}" for index in range(24)
    ]
    geometry_labels = {item["gds_label"] for item in geometry["labels"]}
    if geometry_labels != set(expected_outputs) | {"V3TIELOW"}:
        errors.append("tie overlay does not contain the exact 24 output labels and root label")
    if geometry["counts"] != plan["expected"]:
        errors.append("emitted output-tie geometry differs from the plan")

    log = args.magic_log.read_text(encoding="utf-8", errors="replace")
    metrics: dict[str, int | None] = {}
    for name, pattern in MAGIC_METRICS.items():
        values = [int(value) for value in pattern.findall(log)]
        metrics[name] = values[-1] if values else None
    expected_metrics = {
        "gds_feedback": 0,
        "drc": 0,
        "extraction_feedback": 9,
        "feedback_after_clear": 0,
    }
    if metrics != expected_metrics:
        errors.append(f"Magic metrics differ: {metrics} != {expected_metrics}")
    warning_baseline_exact = args.extraction_feedback.read_bytes() == args.frozen_feedback.read_bytes()
    if not warning_baseline_exact:
        errors.append("Magic extraction warnings differ from the frozen baseline")

    current_count, current_models, current_terminals = spice_population(args.flat_spice)
    source_count, source_models, source_terminals = spice_population(args.source_flat)
    device_population_equal = (
        current_count == source_count == 6037
        and current_models == source_models
        and current_terminals["VDPWR"] == source_terminals["VDPWR"] == 4818
        and current_terminals["VGND"] == source_terminals["VGND"] == 5242
    )
    if not device_population_equal:
        errors.append("device/model or device-terminal supply population changed")

    union = UnionFind()
    top_names = add_connections(union, args.top_ext)
    child_prefix = "v3_digital_output_tie_low_0/"
    child_names = add_connections(union, args.overlay_ext, child_prefix)
    if not child_names:
        errors.append("output-tie overlay extraction contains no connectivity records")
    output_roots = {union.root(label) for label in expected_outputs}
    all_outputs_grounded = (
        len(output_roots) == 1
        and union.root(expected_outputs[0]) == union.root("V3TIELOW")
        and union.root("V3TIELOW") == union.root("VGND")
    )
    if not all_outputs_grounded:
        errors.append("not all 24 digital outputs extract on the VGND network")
    vdpwr_separate = union.root("VDPWR") != union.root("VGND")
    if not vdpwr_separate:
        errors.append("output tie shorts VDPWR to VGND")

    previous_labels = (
        {f"V3R{index:03d}" for index in range(305)}
        | {f"V3H{index:03d}" for index in range(41)}
        | {f"V3B{index:03d}" for index in range(14)}
        | {f"V3I{index:03d}" for index in range(4)}
    )
    tied_previous = sorted(
        label for label in previous_labels
        if union.root(label) in {union.root("VGND"), union.root("VDPWR")}
    )
    if tied_previous:
        errors.append(f"previous signal labels were tied to a supply: {tied_previous}")
    previous_groups: dict[str, list[str]] = defaultdict(list)
    for label in previous_labels:
        previous_groups[union.root(label)].append(label)
    source_union = UnionFind()
    add_connections(source_union, args.source_top_ext)
    source_previous_groups: dict[str, list[str]] = defaultdict(list)
    for label in previous_labels:
        source_previous_groups[source_union.root(label)].append(label)
    previous_partition = sorted(tuple(sorted(labels)) for labels in previous_groups.values())
    source_previous_partition = sorted(
        tuple(sorted(labels)) for labels in source_previous_groups.values()
    )
    previous_partition_preserved = previous_partition == source_previous_partition
    if not previous_partition_preserved:
        errors.append("previous controller/analog route partition differs from the source")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "24 unused TinyTapeout digital outputs tied physically and statically to VGND",
        "errors": errors,
        "checks": {
            "magic_metrics": metrics,
            "extraction_warning_baseline_exact": warning_baseline_exact,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "planned_output_pins": len(plan["pins"]),
            "extracted_output_labels": len(expected_outputs),
            "distinct_output_roots": len(output_roots),
            "all_outputs_tied_to_vgnd": all_outputs_grounded,
            "vdpwr_remains_separate": vdpwr_separate,
            "previous_signal_labels_tied_to_supply": tied_previous,
            "distinct_previous_route_groups": len(previous_groups),
            "source_distinct_previous_route_groups": len(source_previous_groups),
            "previous_route_partition_preserved": previous_partition_preserved,
            "total_extracted_devices": current_count,
            "device_population_matches_source": device_population_equal,
            "vdpwr_terminal_hits": current_terminals["VDPWR"],
            "vgnd_terminal_hits": current_terminals["VGND"],
            "top_connectivity_names": len(top_names),
            "overlay_connectivity_names": len(child_names),
        },
        "pin_mapping": [
            {"internal_label": f"V3O{index:03d}", "pin": name, "value": 0}
            for index, name in enumerate(plan["pins"])
        ],
        "artifact_sha256": {
            "plan": sha256(args.plan),
            "geometry": sha256(args.geometry),
            "assembly": sha256(args.assembly),
            "gds": sha256(args.gds),
            "precheck": sha256(args.precheck),
            "magic_log": sha256(args.magic_log),
            "extraction_feedback": sha256(args.extraction_feedback),
            "top_ext": sha256(args.top_ext),
            "overlay_ext": sha256(args.overlay_ext),
            "flat_spice": sha256(args.flat_spice),
            "source_flat_spice": sha256(args.source_flat),
            "source_top_ext": sha256(args.source_top_ext),
            "auditor": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/digital_output_tie"
    readback = base / "magic_readback"
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/digital_output_tie_plan.json")
    parser.add_argument("--geometry", type=Path, default=base / "direct/route_geometry.json")
    parser.add_argument("--assembly", type=Path, default=base / "direct/assembly_report.json")
    parser.add_argument("--gds", type=Path, default=base / "direct/v3_four_channel_output_tied.gds")
    parser.add_argument("--precheck", type=Path, default=base / "precheck/precheck_summary.json")
    parser.add_argument("--source-gate", type=Path, default=ROOT / "v3/evidence/analog_input_escape_gate.json")
    parser.add_argument("--source-gds", type=Path, default=ROOT / "v3/frozen/analog_input_escapes/v3_four_channel_analog_inputs.gds")
    parser.add_argument("--source-flat", type=Path, default=ROOT / "v3/frozen/analog_input_escapes/v3_four_ch_analog_inputs_flat.spice")
    parser.add_argument("--source-top-ext", type=Path, default=ROOT / "v3/frozen/analog_input_escapes/v3_four_ch_analog_inputs.ext")
    parser.add_argument("--top-ext", type=Path, default=readback / "v3_four_ch_output_tied.ext")
    parser.add_argument("--overlay-ext", type=Path, default=readback / "v3_digital_output_tie_low.ext")
    parser.add_argument("--flat-spice", type=Path, default=readback / "v3_four_ch_output_tied_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=base / "magic_readback.log")
    parser.add_argument("--extraction-feedback", type=Path, default=readback / "extraction_feedback.txt")
    parser.add_argument("--frozen-feedback", type=Path, default=ROOT / "v3/frozen/analog_input_escapes/extraction_feedback.txt")
    parser.add_argument("--output", type=Path, default=base / "topology_audit.json")
    args = parser.parse_args()
    report = validate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
