#!/usr/bin/env python3
"""Audit the exact assembled V3 four-channel analog-input escape GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MERGE_RE = re.compile(r'^merge "([^"]+)" "([^"]+)"')
MAGIC_METRICS = {
    "gds_feedback": re.compile(r"V3_ANALOG_INPUT_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_ANALOG_INPUT_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(r"V3_ANALOG_INPUT_EXTRACTION_FEEDBACK_COUNT=(\d+)"),
    "feedback_after_clear": re.compile(r"V3_ANALOG_INPUT_FEEDBACK_AFTER_CLEAR=(\d+)"),
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


def merge_union(path: Path) -> tuple[UnionFind, set[str]]:
    union = UnionFind()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MERGE_RE.match(line)
        if match:
            union.union(*match.groups())
            names.update(match.groups())
    return union, names


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    assembly = json.loads(args.assembly.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    source_gate = json.loads(args.source_gate.read_text(encoding="utf-8"))

    source = plan["source_checkpoint"]
    if source_gate.get("status") != "pass":
        errors.append("source boundary-handoff gate is not closed")
    if sha256(args.source_gate) != source["physical_gate_sha256"]:
        errors.append("analog-input plan is not bound to the source physical gate")
    if source_gate.get("gds_sha256") != source["sha256"]:
        errors.append("analog-input plan is not bound to the closed source GDS")
    if sha256(args.source_gds) != source["sha256"]:
        errors.append("source GDS differs from the analog-input route contract")
    if geometry.get("status") != "generated from hash-locked, exact-translation analog-input plan":
        errors.append("analog-input geometry provenance is not closed")
    if assembly.get("status") != "pass":
        errors.append("direct GDS assembly report is not clean")
    if assembly.get("output_sha256") != sha256(args.gds):
        errors.append("assembly output hash differs from the GDS under audit")
    if assembly.get("geometry_sha256") != sha256(args.geometry):
        errors.append("assembly report does not bind the route geometry")
    if precheck.get("gds_sha256") != sha256(args.gds):
        errors.append("direct-GDS precheck refers to another GDS")
    if precheck.get("status") != "pass" or any(
        item["markers"] != 0 for item in precheck["checks"].values()
    ):
        errors.append("direct-GDS geometry precheck is not clean")

    route_rows = geometry["routes"]
    identical_layer_sequences = len({tuple(item["layers"]) for item in route_rows}) == 1
    identical_via_counts = len({item["via_count"] for item in route_rows}) == 1
    identical_lengths = len({item["m3_centerline_length_um"] for item in route_rows}) == 1
    zero_direction_reversals = all(item["direction_reversals"] == 0 for item in route_rows)
    if not all((identical_layer_sequences, identical_via_counts, identical_lengths, zero_direction_reversals)):
        errors.append("four analog-input routes are not exact matched translations")
    expected_terminals = sorted(
        (item["net"], tuple(float(value) for value in item["pin_rect"]))
        for item in plan["channels"]
    )
    observed_terminals = sorted(
        (item["net"], tuple(float(value) for value in item["bbox_um"]))
        for item in geometry["shapes"]
        if item.get("kind") == "exact_tinytapeout_analog_terminal"
    )
    exact_terminals = observed_terminals == expected_terminals
    if not exact_terminals:
        errors.append("analog terminal rectangles differ from the official template")

    expected_metrics = {
        "gds_feedback": 0,
        "drc": 0,
        "extraction_feedback": 9,
        "feedback_after_clear": 0,
    }
    log = args.magic_log.read_text(encoding="utf-8", errors="replace")
    metrics: dict[str, int | None] = {}
    for name, pattern in MAGIC_METRICS.items():
        values = [int(value) for value in pattern.findall(log)]
        metrics[name] = values[-1] if values else None
    if metrics != expected_metrics:
        errors.append(f"Magic metrics differ: {metrics} != {expected_metrics}")
    warning_baseline_exact = (
        args.extraction_feedback.read_bytes() == args.frozen_feedback.read_bytes()
    )
    if not warning_baseline_exact:
        errors.append("extraction feedback differs from the frozen analog baseline")

    current_count, current_models, current_terminals = spice_population(args.flat_spice)
    source_count, source_models, source_terminals = spice_population(args.source_flat)
    device_population_equal = (
        current_count == source_count == 6037
        and current_models == source_models
        and current_terminals["VDPWR"] == source_terminals["VDPWR"] == 4818
        and current_terminals["VGND"] == source_terminals["VGND"] == 5242
    )
    if not device_population_equal:
        errors.append("device/model or supply population changed during analog-input routing")

    overlay_nodes = {
        match.group(1)
        for match in re.finditer(
            r'^node "([^"]+)"',
            args.overlay_ext.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    expected_inputs = {f"V3I{index:03d}" for index in range(4)}
    if overlay_nodes != expected_inputs:
        errors.append("standalone input overlay does not contain exactly four nets")

    union, merge_names = merge_union(args.top_ext)
    source_union, _ = merge_union(args.source_top_ext)

    previous_labels = (
        {f"V3R{index:03d}" for index in range(305)}
        | {f"V3H{index:03d}" for index in range(41)}
        | {f"V3B{index:03d}" for index in range(14)}
    )
    previous_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(previous_labels):
        previous_roots[union.root(label)].append(label)
    source_previous_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(previous_labels):
        source_previous_roots[source_union.root(label)].append(label)
    previous_partition = sorted(tuple(labels) for labels in previous_roots.values())
    source_previous_partition = sorted(
        tuple(labels) for labels in source_previous_roots.values()
    )
    previous_partition_preserved = previous_partition == source_previous_partition
    if not previous_partition_preserved:
        errors.append("previously closed controller/boundary/analog net partition changed")
    supply_roots = {union.root("VDPWR"), union.root("VGND")}
    if len(supply_roots) != 2:
        errors.append("VDPWR and VGND are electrically equivalent")

    input_reports: list[dict[str, Any]] = []
    input_roots: dict[str, list[str]] = defaultdict(list)
    for channel in plan["channels"]:
        index = int(channel["channel"])
        label = f"V3I{index:03d}"
        physical_instance = 3 - index
        expected_suffix = (
            f"v3_channel_selector_late_promotion_{physical_instance}/"
            "v3_channel_input_bias_late_promotion_0/element_input"
        )
        root = union.root(label)
        input_roots[root].append(label)
        observed_targets = sorted(
            name for name in merge_names
            if union.root(name) == root and name.endswith("/element_input")
        )
        expected_targets = [name for name in observed_targets if name.endswith(expected_suffix)]
        other_previous = sorted(
            prior for prior in previous_labels if union.root(prior) == root
        )
        if len(observed_targets) != 1 or len(expected_targets) != 1:
            errors.append(
                f"{channel['net']}: extracted element-input targets {observed_targets} do not match {expected_suffix}"
            )
        if other_previous:
            errors.append(f"{channel['net']}: input is shorted to previously routed labels")
        if root in supply_roots:
            errors.append(f"{channel['net']}: input is shorted to a supply")
        if current_terminals[label] != 16:
            errors.append(f"{channel['net']}: expected 16 device-terminal hits, got {current_terminals[label]}")
        input_reports.append({
            "channel": index,
            "logical_net": channel["net"],
            "tinytapeout_pin": channel["pin"],
            "input_label": label,
            "expected_target_suffix": expected_suffix,
            "observed_element_input_targets": observed_targets,
            "previous_labels_in_group": other_previous,
            "shorted_to_supply": root in supply_roots,
            "device_terminal_hits": current_terminals[label],
        })

    aliased_inputs = [labels for labels in input_roots.values() if len(labels) != 1]
    if aliased_inputs:
        errors.append(f"analog inputs became mutually aliased: {aliased_inputs}")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "four exact translated TinyTapeout analog-input pad escapes through M4/Via3/M3/Via2/M2 into four independent channel input rails",
        "errors": errors,
        "checks": {
            "magic_metrics": metrics,
            "extraction_warning_baseline_exact": warning_baseline_exact,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "overlay_input_nodes": len(overlay_nodes),
            "distinct_input_groups": len(input_roots),
            "input_routes_shorted_to_supply": sum(union.root(label) in supply_roots for label in expected_inputs),
            "input_routes_shorted_to_previous_labels": sum(
                any(union.root(label) == union.root(prior) for prior in previous_labels)
                for label in expected_inputs
            ),
            "distinct_previous_route_groups": len(previous_roots),
            "previous_route_partition_preserved": previous_partition_preserved,
            "exact_tinytapeout_analog_terminals": exact_terminals,
            "identical_layer_sequences": identical_layer_sequences,
            "identical_via_counts": identical_via_counts,
            "identical_centerline_lengths": identical_lengths,
            "zero_direction_reversals": zero_direction_reversals,
            "input_device_terminal_hits": {
                label: current_terminals[label] for label in sorted(expected_inputs)
            },
            "total_extracted_devices": current_count,
            "model_population": dict(sorted(current_models.items())),
            "device_population_matches_source": device_population_equal,
            "vdpwr_terminal_hits": current_terminals["VDPWR"],
            "vgnd_terminal_hits": current_terminals["VGND"],
        },
        "inputs": input_reports,
        "artifact_sha256": {
            "gds": sha256(args.gds),
            "plan": sha256(args.plan),
            "geometry": sha256(args.geometry),
            "assembly": sha256(args.assembly),
            "precheck": sha256(args.precheck),
            "source_gate": sha256(args.source_gate),
            "source_flat_spice": sha256(args.source_flat),
            "source_top_ext": sha256(args.source_top_ext),
            "magic_log": sha256(args.magic_log),
            "extraction_feedback": sha256(args.extraction_feedback),
            "flat_spice": sha256(args.flat_spice),
            "top_ext": sha256(args.top_ext),
            "overlay_ext": sha256(args.overlay_ext),
            "auditor": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/analog_input_escapes"
    direct = base / "direct"
    readback = base / "magic_readback"
    parser.add_argument("--gds", type=Path, default=direct / "v3_four_channel_analog_inputs.gds")
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/analog_input_escape_plan.json")
    parser.add_argument("--geometry", type=Path, default=direct / "route_geometry.json")
    parser.add_argument("--assembly", type=Path, default=direct / "assembly_report.json")
    parser.add_argument("--precheck", type=Path, default=base / "precheck/precheck_summary.json")
    parser.add_argument("--source-gate", type=Path, default=ROOT / "v3/evidence/physical_control_boundary_handoff_gate.json")
    parser.add_argument("--source-gds", type=Path, default=ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_channel_ctrl_boundary_handoffs.gds")
    parser.add_argument("--source-flat", type=Path, default=ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_ch_ctrl_boundary_handoff_flat.spice")
    parser.add_argument("--source-top-ext", type=Path, default=ROOT / "v3/frozen/controller_boundary_handoffs/v3_four_ch_ctrl_boundary_handoff.ext")
    parser.add_argument("--magic-log", type=Path, default=readback / "magic_readback.log")
    parser.add_argument("--extraction-feedback", type=Path, default=readback / "extraction_feedback.txt")
    parser.add_argument("--frozen-feedback", type=Path, default=ROOT / "v3/frozen/controller_boundary_handoffs/extraction_feedback.txt")
    parser.add_argument("--flat-spice", type=Path, default=readback / "v3_four_ch_analog_inputs_flat.spice")
    parser.add_argument("--top-ext", type=Path, default=readback / "v3_four_ch_analog_inputs.ext")
    parser.add_argument("--overlay-ext", type=Path, default=readback / "v3_analog_input_escape_routes.ext")
    parser.add_argument("--report", type=Path, default=base / "input_topology_audit.json")
    args = parser.parse_args()
    report = validate(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "errors": report["errors"],
        "checks": report["checks"],
    }, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
