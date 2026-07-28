#!/usr/bin/env python3
"""Audit the exact assembled V3 controller-to-TinyTapeout input handoffs."""

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
BOUNDARY_RE = re.compile(r"V3B\d{3}")
INTERNAL_HANDOFF_RE = re.compile(r"V3H\d{3}")
MERGE_RE = re.compile(r'^merge "([^"]+)" "([^"]+)"')
MAGIC_METRICS = {
    "gds_feedback": re.compile(r"V3_CONTROL_BOUNDARY_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_CONTROL_BOUNDARY_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(
        r"V3_CONTROL_BOUNDARY_EXTRACTION_FEEDBACK_COUNT=(\d+)"
    ),
    "feedback_after_clear": re.compile(
        r"V3_CONTROL_BOUNDARY_FEEDBACK_AFTER_CLEAR=(\d+)"
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


def spice_population(path: Path) -> tuple[int, Counter[str], Counter[str]]:
    device_count = 0
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
        device_count += 1
        models[tokens[model_index]] += 1
        terminals.update(tokens[1:model_index])
    return device_count, models, terminals


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    route_plan = json.loads(args.route_plan.read_text(encoding="utf-8"))
    summary = json.loads(args.input_summary.read_text(encoding="utf-8"))
    route_audit = json.loads(args.route_audit.read_text(encoding="utf-8"))
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    assembly = json.loads(args.assembly.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    source_gate = json.loads(args.source_gate.read_text(encoding="utf-8"))
    source_routes = json.loads(args.source_routes.read_text(encoding="utf-8"))

    if source_gate.get("status") != "pass":
        errors.append("source controller/analog handoff gate is not closed")
    if source_gate.get("gds_sha256") != plan["source_checkpoint"]["sha256"]:
        errors.append("boundary plan is not bound to the closed source GDS")
    if sha256(args.source_gds) != plan["source_checkpoint"]["sha256"]:
        errors.append("source controller/analog handoff GDS differs from the route contract")
    if route_audit.get("status") != "pass" or route_audit.get("errors"):
        errors.append("independent OpenROAD boundary-route audit is not clean")
    if geometry.get("status") != "generated from hash-locked, graph-audited OpenROAD routes":
        errors.append("direct boundary geometry did not come from the audited route graph")
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
        errors.append("device/model or supply population changed during boundary routing")

    overlay_nodes = {
        match.group(1)
        for match in re.finditer(
            r'^node "([^"]+)"',
            args.overlay_ext.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    expected_boundaries = {f"V3B{index:03d}" for index in range(14)}
    if overlay_nodes != expected_boundaries:
        errors.append("standalone boundary overlay does not contain exactly 14 routed nets")

    union = UnionFind()
    for line in args.top_ext.read_text(encoding="utf-8").splitlines():
        match = MERGE_RE.match(line)
        if match:
            union.union(*match.groups())

    expected_ctrl = {f"V3R{index:03d}" for index in range(305)}
    expected_internal_handoffs = {f"V3H{index:03d}" for index in range(41)}
    ctrl_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(expected_ctrl):
        ctrl_roots[union.root(label)].append(label)
    ctrl_aliases = [labels for labels in ctrl_roots.values() if len(labels) != 1]
    if ctrl_aliases:
        errors.append(f"controller routes became mutually aliased: {ctrl_aliases[:4]}")
    internal_handoff_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(expected_internal_handoffs):
        internal_handoff_roots[union.root(label)].append(label)
    internal_handoff_aliases = [
        labels for labels in internal_handoff_roots.values() if len(labels) != 1
    ]
    if internal_handoff_aliases:
        errors.append(
            f"previously closed internal handoffs became aliased: {internal_handoff_aliases[:4]}"
        )
    supply_roots = {union.root("VDPWR"), union.root("VGND")}
    if len(supply_roots) != 2:
        errors.append("VDPWR and VGND are electrically equivalent")

    source_label_for_logical = {
        logical: f"V3R{int(route_id[1:]):03d}"
        for route_id, logical in source_routes["net_ids"].items()
    }
    geometry_label_for_logical = {
        logical: label for label, logical in geometry["label_net_map"].items()
    }
    expected_logical = {net["net"] for net in summary["nets"]}
    if set(geometry_label_for_logical) != expected_logical:
        errors.append("route geometry labels do not cover the boundary manifest")

    expected_terminals = sorted(
        (
            summary["net_ids"][f"N{int(pin_id[1:4]):03d}"],
            endpoint["layer"],
            tuple(float(value) for value in endpoint["rect_um"]),
        )
        for pin_id, endpoint in summary["pins"].items()
        if endpoint.get("role") == "tinytapeout_input_pin"
    )
    observed_terminals = sorted(
        (item["net"], item["layer"], tuple(float(value) for value in item["bbox_um"]))
        for item in geometry["shapes"]
        if item.get("kind") == "exact_tinytapeout_input_terminal"
    )
    exact_boundary_terminals = expected_terminals == observed_terminals
    if not exact_boundary_terminals:
        errors.append("emitted boundary terminals differ from the official pin rectangles")
    if len(observed_terminals) != route_plan["expected_boundary_terminal_count"]:
        errors.append("boundary terminal count differs from the frozen route plan")

    handoff_reports: list[dict[str, Any]] = []
    boundary_roots: dict[str, list[str]] = defaultdict(list)
    for net in summary["nets"]:
        logical = net["net"]
        boundary = geometry_label_for_logical.get(logical, "MISSING")
        expected_route = source_label_for_logical.get(logical, "MISSING")
        root = union.root(boundary)
        boundary_roots[root].append(boundary)
        controller_labels = sorted(
            label for label in expected_ctrl if union.root(label) == root
        )
        internal_labels = sorted(
            label for label in expected_internal_handoffs if union.root(label) == root
        )
        if controller_labels != [expected_route]:
            errors.append(
                f"{logical}: extracted controller endpoint {controller_labels} != {expected_route}"
            )
        if internal_labels:
            errors.append(f"{logical}: boundary input is shorted to internal analog handoffs")
        if root in supply_roots:
            errors.append(f"{logical}: boundary input is shorted to a supply")
        handoff_reports.append({
            "boundary_label": boundary,
            "logical_net": logical,
            "tinytapeout_pin": plan["pin_mapping"][logical],
            "controller_route": expected_route,
            "controller_labels_in_group": controller_labels,
            "internal_handoff_labels_in_group": internal_labels,
            "shorted_to_supply": root in supply_roots,
        })

    aliased_boundaries = [labels for labels in boundary_roots.values() if len(labels) != 1]
    if aliased_boundaries:
        errors.append(f"boundary inputs became mutually aliased: {aliased_boundaries[:4]}")

    flat_text = args.flat_spice.read_text(encoding="utf-8")
    ctrl_labels_in_flat = {match.group(0) for match in CTRL_ROUTE_RE.finditer(flat_text)}
    if ctrl_labels_in_flat != expected_ctrl:
        errors.append("flattened extraction text does not preserve all controller labels")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "exact assembled V3 controller-to-TinyTapeout boundary GDS: 14 distinct digital input handoffs on 28 endpoints with official terminal rectangles",
        "errors": errors,
        "checks": {
            "magic_metrics": metrics,
            "extraction_warning_baseline_exact": warning_baseline_exact,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "openroad_route_graph_audit": route_audit.get("status"),
            "overlay_boundary_nodes": len(overlay_nodes),
            "distinct_boundary_groups": len(boundary_roots),
            "boundary_inputs_shorted_to_supply": sum(
                union.root(label) in supply_roots for label in expected_boundaries
            ),
            "boundary_inputs_shorted_to_internal_handoffs": sum(
                any(union.root(label) == union.root(internal) for internal in expected_internal_handoffs)
                for label in expected_boundaries
            ),
            "distinct_controller_route_groups": len(ctrl_roots),
            "distinct_internal_handoff_groups": len(internal_handoff_roots),
            "controller_labels_in_flat_extraction_text": len(ctrl_labels_in_flat),
            "exact_tinytapeout_boundary_terminals": exact_boundary_terminals,
            "tinytapeout_boundary_terminal_count": len(observed_terminals),
            "total_extracted_devices": current_count,
            "model_population": dict(sorted(current_models.items())),
            "device_population_matches_source": device_population_equal,
            "vdpwr_terminal_hits": current_terminals["VDPWR"],
            "vgnd_terminal_hits": current_terminals["VGND"],
        },
        "handoffs": handoff_reports,
        "artifact_sha256": {
            "gds": sha256(args.gds),
            "plan": sha256(args.plan),
            "route_plan": sha256(args.route_plan),
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
    base = ROOT / "build/v3/control_boundary_handoffs"
    direct = base / "direct"
    readback = base / "magic_readback"
    openroad = base / "openroad"
    parser.add_argument("--gds", type=Path, default=direct / "v3_four_channel_ctrl_boundary_handoffs.gds")
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/physical_control_boundary_handoff_plan.json")
    parser.add_argument("--route-plan", type=Path, default=ROOT / "v3/layout/physical_control_boundary_handoff_route_plan.json")
    parser.add_argument("--input-summary", type=Path, default=openroad / "input_summary.json")
    parser.add_argument("--route-audit", type=Path, default=openroad / "route_audit.json")
    parser.add_argument("--geometry", type=Path, default=direct / "route_geometry.json")
    parser.add_argument("--assembly", type=Path, default=direct / "assembly_report.json")
    parser.add_argument("--precheck", type=Path, default=base / "precheck/precheck_summary.json")
    parser.add_argument("--source-gate", type=Path, default=ROOT / "v3/evidence/physical_control_analog_handoff_gate.json")
    parser.add_argument("--source-gds", type=Path, default=ROOT / "v3/frozen/controller_analog_handoffs/v3_four_channel_ctrl_analog_handoffs.gds")
    parser.add_argument("--source-routes", type=Path, default=ROOT / "v3/frozen/controller_signal_routing/input_summary.json")
    parser.add_argument("--source-flat", type=Path, default=ROOT / "v3/frozen/controller_analog_handoffs/v3_four_ch_ctrl_analog_handoff_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=readback / "magic_readback.log")
    parser.add_argument("--extraction-feedback", type=Path, default=readback / "extraction_feedback.txt")
    parser.add_argument("--frozen-feedback", type=Path, default=ROOT / "v3/frozen/controller_analog_handoffs/extraction_feedback.txt")
    parser.add_argument("--flat-spice", type=Path, default=readback / "v3_four_ch_ctrl_boundary_handoff_flat.spice")
    parser.add_argument("--top-ext", type=Path, default=readback / "v3_four_ch_ctrl_boundary_handoff.ext")
    parser.add_argument("--overlay-ext", type=Path, default=readback / "v3_ctrl_boundary_handoff_routes.ext")
    parser.add_argument("--report", type=Path, default=base / "boundary_topology_audit.json")
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
