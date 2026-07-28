#!/usr/bin/env python3
"""Audit the exact assembled V3 controller-to-analog handoff GDS.

This is deliberately separate from the OpenROAD route-graph checker.  It
proves that the geometry which Magic actually extracted joins each handoff to
one, and only one, controller route and to the intended analog endpoint.  The
phase-tree assertion is made from the flattened device netlist; hierarchical
``.ext`` merge text is not a reliable enumeration of every leaf of an already
connected tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CTRL_ROUTE_RE = re.compile(r"V3R\d{3}")
HANDOFF_RE = re.compile(r"V3H\d{3}")
MERGE_RE = re.compile(r'^merge "([^"]+)" "([^"]+)"')
SELECTOR_TARGET_RE = re.compile(
    r"v3_channel_selector_late_promotion_([0-3])/v3_selector_route_pilot_0/"
    r"(group[0-3]_bit[01]|channel_enable|mixers_blank)$"
)
MAGIC_METRICS = {
    "gds_feedback": re.compile(r"V3_CONTROL_HANDOFF_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_CONTROL_HANDOFF_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(
        r"V3_CONTROL_HANDOFF_EXTRACTION_FEEDBACK_COUNT=(\d+)"
    ),
    "feedback_after_clear": re.compile(
        r"V3_CONTROL_HANDOFF_FEEDBACK_AFTER_CLEAR=(\d+)"
    ),
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


def spice_population(path: Path) -> tuple[list[list[str]], Counter[str], Counter[str]]:
    rows: list[list[str]] = []
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
        nodes = tokens[1:model_index]
        rows.append(nodes)
        models[tokens[model_index]] += 1
        terminals.update(nodes)
    return rows, models, terminals


def expected_target_suffixes(net: dict[str, Any]) -> list[str]:
    """Translate logical channel numbering to the physical left-right instances."""

    result: list[str] = []
    for target in net["targets"]:
        match = re.fullmatch(
            r"channel([0-3])\.(group[0-3]_bit[01]|channel_enable|mixers_blank)",
            target["logical"],
        )
        if not match:
            continue
        logical_channel, port = int(match.group(1)), match.group(2)
        physical_instance = 3 - logical_channel
        result.append(
            f"v3_channel_selector_late_promotion_{physical_instance}/"
            f"v3_selector_route_pilot_0/{port}"
        )
    return sorted(result)


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    summary = json.loads(args.input_summary.read_text(encoding="utf-8"))
    route_audit = json.loads(args.route_audit.read_text(encoding="utf-8"))
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    assembly = json.loads(args.assembly.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    source_gate = json.loads(args.source_gate.read_text(encoding="utf-8"))
    source_routes = json.loads(args.source_routes.read_text(encoding="utf-8"))

    if source_gate.get("status") != "pass":
        errors.append("source controller-power gate is not closed")
    if source_gate.get("gds_sha256") != plan["source_checkpoint"]["sha256"]:
        errors.append("handoff plan is not bound to the closed controller-power GDS")
    if sha256(args.source_gds) != plan["source_checkpoint"]["sha256"]:
        errors.append("source controller-power GDS differs from the route contract")
    if route_audit.get("status") != "pass" or route_audit.get("errors"):
        errors.append("independent OpenROAD route-graph audit is not clean")
    if geometry.get("status") != "generated from hash-locked, graph-audited OpenROAD routes":
        errors.append("direct route geometry did not come from the audited route graph")
    if assembly.get("status") != "pass":
        errors.append("direct GDS assembly report is not clean")
    if assembly.get("output_sha256") != sha256(args.gds):
        errors.append("assembly output hash differs from the GDS under audit")
    if precheck.get("gds_sha256") != sha256(args.gds):
        errors.append("direct-GDS precheck refers to another GDS")
    if precheck.get("status") != "pass" or any(
        item["markers"] != 0 for item in precheck["checks"].values()
    ):
        errors.append("direct-GDS geometry precheck is not clean")

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

    current_rows, current_models, current_terminals = spice_population(args.flat_spice)
    source_rows, source_models, source_terminals = spice_population(args.source_flat)
    device_population_equal = (
        len(current_rows) == len(source_rows) == 6037
        and current_models == source_models
        and current_terminals["VDPWR"] == source_terminals["VDPWR"] == 4818
        and current_terminals["VGND"] == source_terminals["VGND"] == 5242
    )
    if not device_population_equal:
        errors.append("device/model or supply-terminal population changed during handoff routing")

    overlay_nodes = {
        match.group(1)
        for match in re.finditer(
            r'^node "([^"]+)"',
            args.overlay_ext.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    expected_handoffs = {f"V3H{index:03d}" for index in range(41)}
    if overlay_nodes != expected_handoffs:
        errors.append("standalone extracted overlay does not contain exactly 41 handoff nets")

    union = UnionFind()
    merge_names: set[str] = set()
    for line in args.top_ext.read_text(encoding="utf-8").splitlines():
        match = MERGE_RE.match(line)
        if match:
            first, second = match.groups()
            union.union(first, second)
            merge_names.update((first, second))

    expected_ctrl = {f"V3R{index:03d}" for index in range(305)}
    ctrl_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(expected_ctrl):
        ctrl_roots[union.root(label)].append(label)
    ctrl_aliases = [labels for labels in ctrl_roots.values() if len(labels) != 1]
    if ctrl_aliases:
        errors.append(f"controller routes became mutually aliased: {ctrl_aliases[:4]}")
    supply_roots = {union.root("VDPWR"), union.root("VGND")}
    if len(supply_roots) != 2:
        errors.append("VDPWR and VGND are electrically equivalent")
    routes_to_supply = [
        label for label in sorted(expected_ctrl)
        if union.root(label) in supply_roots
    ]
    if routes_to_supply:
        errors.append(f"controller routes are shorted to supply: {routes_to_supply[:4]}")

    source_label_for_logical = {
        logical: f"V3R{int(route_id[1:]):03d}"
        for route_id, logical in source_routes["net_ids"].items()
    }
    geometry_label_for_logical = {
        logical: label for label, logical in geometry["label_net_map"].items()
    }
    if set(geometry_label_for_logical) != {net["net"] for net in summary["nets"]}:
        errors.append("route geometry labels do not cover the logical handoff manifest")

    handoff_reports: list[dict[str, Any]] = []
    handoff_roots: dict[str, list[str]] = defaultdict(list)
    for net in summary["nets"]:
        logical = net["net"]
        handoff = geometry_label_for_logical.get(logical, "MISSING")
        expected_route = source_label_for_logical.get(logical, "MISSING")
        root = union.root(handoff)
        handoff_roots[root].append(handoff)
        controller_labels = sorted(
            label for label in expected_ctrl if union.root(label) == root
        )
        if controller_labels != [expected_route]:
            errors.append(
                f"{logical}: extracted controller endpoint {controller_labels} != {expected_route}"
            )
        if root in supply_roots:
            errors.append(f"{logical}: handoff is shorted to a supply")

        required_suffixes = expected_target_suffixes(net)
        observed_targets = sorted(
            name for name in merge_names
            if union.root(name) == root and SELECTOR_TARGET_RE.search(name)
        )
        observed_suffixes = sorted(
            SELECTOR_TARGET_RE.search(name).group(0)  # type: ignore[union-attr]
            for name in observed_targets
        )
        if net["route_class"] != "phase" and observed_suffixes != required_suffixes:
            errors.append(
                f"{logical}: extracted analog targets {observed_suffixes} != {required_suffixes}"
            )

        handoff_reports.append({
            "handoff": handoff,
            "logical_net": logical,
            "route_class": net["route_class"],
            "controller_route": expected_route,
            "controller_labels_in_group": controller_labels,
            "expected_analog_target_suffixes": required_suffixes,
            "observed_analog_target_suffixes": observed_suffixes,
            "shorted_to_supply": root in supply_roots,
        })

    aliased_handoffs = [labels for labels in handoff_roots.values() if len(labels) != 1]
    if aliased_handoffs:
        errors.append(f"handoff nets became mutually aliased: {aliased_handoffs[:4]}")

    phase_terminal_hits: dict[str, int] = {}
    phase_channels: dict[str, list[int]] = {}
    for phase_index in range(4):
        route = source_label_for_logical[f"phase_wave[{phase_index}]"]
        phase_rows = [
            nodes for nodes in current_rows
            if route in nodes
            and any("v3_channel_selector_late_promotion_" in node for node in nodes)
        ]
        phase_terminal_hits[route] = sum(nodes.count(route) for nodes in phase_rows)
        phase_channels[route] = sorted({
            int(match.group(1))
            for nodes in phase_rows
            for node in nodes
            if (match := re.search(r"v3_channel_selector_late_promotion_([0-3])/", node))
        })
        if phase_terminal_hits[route] != 32 or phase_channels[route] != [0, 1, 2, 3]:
            errors.append(
                f"phase_wave[{phase_index}] does not reach 32 selector terminals in all channels"
            )

    all_ctrl_labels_in_flat_text = {
        match.group(0) for match in CTRL_ROUTE_RE.finditer(
            args.flat_spice.read_text(encoding="utf-8")
        )
    }
    if all_ctrl_labels_in_flat_text != expected_ctrl:
        errors.append("flattened extraction text does not preserve all 305 controller labels")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "exact assembled V3 controller-to-analog handoff GDS: 41 routed nets, 85 endpoints, four phase trees, static selector control, and preserved source topology",
        "errors": errors,
        "checks": {
            "magic_metrics": metrics,
            "extraction_warning_baseline_exact": warning_baseline_exact,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "openroad_route_graph_audit": route_audit.get("status"),
            "overlay_handoff_nodes": len(overlay_nodes),
            "distinct_handoff_groups": len(handoff_roots),
            "handoffs_shorted_to_supply": sum(
                union.root(label) in supply_roots for label in expected_handoffs
            ),
            "distinct_controller_route_groups": len(ctrl_roots),
            "controller_routes_shorted_to_supply": len(routes_to_supply),
            "controller_labels_in_flat_extraction_text": len(all_ctrl_labels_in_flat_text),
            "total_extracted_devices": len(current_rows),
            "model_population": dict(sorted(current_models.items())),
            "device_population_matches_powered_source": device_population_equal,
            "vdpwr_terminal_hits": current_terminals["VDPWR"],
            "vgnd_terminal_hits": current_terminals["VGND"],
            "phase_selector_terminal_hits": phase_terminal_hits,
            "phase_selector_channels": phase_channels,
        },
        "handoffs": handoff_reports,
        "artifact_sha256": {
            "gds": sha256(args.gds),
            "plan": sha256(args.plan),
            "input_summary": sha256(args.input_summary),
            "route_audit": sha256(args.route_audit),
            "geometry": sha256(args.geometry),
            "assembly": sha256(args.assembly),
            "precheck": sha256(args.precheck),
            "source_gate": sha256(args.source_gate),
            "source_routes": sha256(args.source_routes),
            "source_flat_spice": sha256(args.source_flat),
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
    base = ROOT / "build/v3/control_analog_handoffs"
    direct = base / "direct"
    readback = base / "magic_readback"
    openroad = base / "openroad"
    parser.add_argument("--gds", type=Path, default=direct / "v3_four_channel_ctrl_analog_handoffs.gds")
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/physical_control_analog_handoff_plan.json")
    parser.add_argument("--input-summary", type=Path, default=openroad / "input_summary.json")
    parser.add_argument("--route-audit", type=Path, default=openroad / "route_audit.json")
    parser.add_argument("--geometry", type=Path, default=direct / "route_geometry.json")
    parser.add_argument("--assembly", type=Path, default=direct / "assembly_report.json")
    parser.add_argument("--precheck", type=Path, default=base / "precheck/precheck_summary.json")
    parser.add_argument("--source-gate", type=Path, default=ROOT / "v3/evidence/physical_control_power_gate.json")
    parser.add_argument("--source-gds", type=Path, default=ROOT / "v3/frozen/controller_power/v3_four_channel_ctrl_powered.gds")
    parser.add_argument("--source-routes", type=Path, default=ROOT / "v3/frozen/controller_signal_routing/input_summary.json")
    parser.add_argument("--source-flat", type=Path, default=ROOT / "v3/frozen/controller_power/v3_four_channel_ctrl_powered_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=readback / "magic_readback.log")
    parser.add_argument("--extraction-feedback", type=Path, default=readback / "extraction_feedback.txt")
    parser.add_argument("--frozen-feedback", type=Path, default=ROOT / "v3/frozen/controller_power/extraction_feedback.txt")
    parser.add_argument("--flat-spice", type=Path, default=readback / "v3_four_ch_ctrl_analog_handoff_flat.spice")
    parser.add_argument("--top-ext", type=Path, default=readback / "v3_four_ch_ctrl_analog_handoff.ext")
    parser.add_argument("--overlay-ext", type=Path, default=readback / "v3_ctrl_analog_handoff_routes.ext")
    parser.add_argument("--report", type=Path, default=base / "handoff_topology_audit.json")
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
