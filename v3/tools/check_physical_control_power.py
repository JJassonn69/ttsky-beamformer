#!/usr/bin/env python3
"""Audit extracted topology of the exact V3 controller-power GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTE_RE = re.compile(r"V3R\d{3}")
MERGE_RE = re.compile(r'^merge "([^"]+)" "([^"]+)"')
MAGIC_METRICS = {
    "gds_feedback": re.compile(r"V3_CONTROL_POWER_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_CONTROL_POWER_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(
        r"V3_CONTROL_POWER_EXTRACTION_FEEDBACK_COUNT=(\d+)"
    ),
    "feedback_after_clear": re.compile(
        r"V3_CONTROL_POWER_FEEDBACK_AFTER_CLEAR=(\d+)"
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


def is_digital(nodes: list[str]) -> bool:
    return any(
        "sky130_fd_sc_hd__" in node or ROUTE_RE.fullmatch(node)
        for node in nodes
    )


def rail_counts(rows: list[tuple[list[str], str]], digital: bool) -> dict[str, int]:
    counts = Counter(
        node
        for nodes, _model in rows
        if is_digital(nodes) == digital
        for node in nodes
    )
    return {
        "devices": sum(is_digital(nodes) == digital for nodes, _model in rows),
        "VDPWR_terminal_hits": counts["VDPWR"],
        "VGND_terminal_hits": counts["VGND"],
        "stale_VPB_terminal_hits": sum(
            value for name, value in counts.items() if name.endswith("/VPB")
        ),
        "stale_VPWR_terminal_hits": sum(
            value for name, value in counts.items() if name.endswith("/VPWR")
        ),
        "stale_hierarchical_VGND_terminal_hits": sum(
            value for name, value in counts.items() if name.endswith("/VGND")
        ),
    }


def validate(args: argparse.Namespace) -> dict[str, object]:
    errors: list[str] = []
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    source_gate = json.loads(args.source_gate.read_text(encoding="utf-8"))
    if geometry.get("status") != "pass" or geometry.get("errors"):
        errors.append("generated controller-power geometry did not pass its local audit")
    if source_gate.get("status") != "pass":
        errors.append("source controller-signal gate is not closed")
    if precheck.get("status") != "pass" or any(
        item["markers"] != 0 for item in precheck["checks"].values()
    ):
        errors.append("direct-GDS geometry precheck is not clean")

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
    warning_baseline_exact = (
        args.extraction_feedback.read_bytes() == args.frozen_feedback.read_bytes()
    )
    if not warning_baseline_exact:
        errors.append("extraction feedback differs from the frozen analog baseline")

    rows: list[tuple[list[str], str]] = []
    flat_labels: set[str] = set()
    for line in args.flat_spice.read_text(encoding="utf-8").splitlines():
        if not line.startswith("X"):
            continue
        tokens = line.split()
        model_index = next(
            index for index, token in enumerate(tokens) if token.startswith("sky130_fd_pr__")
        )
        nodes = tokens[1:model_index]
        rows.append((nodes, tokens[model_index]))
        flat_labels.update(node for node in nodes if ROUTE_RE.fullmatch(node))

    expected_labels = {f"V3R{index:03d}" for index in range(305)}
    if flat_labels != expected_labels:
        errors.append("flat extraction loses or aliases controller route labels")
    analog = rail_counts(rows, False)
    digital = rail_counts(rows, True)
    expected_analog = {
        "devices": 1315,
        "VDPWR_terminal_hits": 740,
        "VGND_terminal_hits": 1360,
        "stale_VPB_terminal_hits": 0,
        "stale_VPWR_terminal_hits": 0,
        "stale_hierarchical_VGND_terminal_hits": 0,
    }
    expected_digital = {
        "devices": 4722,
        "VDPWR_terminal_hits": 4078,
        "VGND_terminal_hits": 3882,
        "stale_VPB_terminal_hits": 0,
        "stale_VPWR_terminal_hits": 0,
        "stale_hierarchical_VGND_terminal_hits": 0,
    }
    if analog != expected_analog:
        errors.append(f"analog device/power population changed: {analog}")
    if digital != expected_digital:
        errors.append(f"digital device/power population differs: {digital}")
    if len(rows) != 6037:
        errors.append(f"total extracted device count {len(rows)} != 6037")

    overlay_nodes = {
        match.group(1)
        for match in re.finditer(
            r'^node "([^"]+)"',
            args.overlay_ext.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    if overlay_nodes != {"VDPWR", "VGND"}:
        errors.append(f"power overlay nodes differ: {sorted(overlay_nodes)}")

    union = UnionFind()
    for line in args.top_ext.read_text(encoding="utf-8").splitlines():
        match = MERGE_RE.match(line)
        if match:
            union.union(match.group(1), match.group(2))
    vdpwr_root = union.root("VDPWR")
    vgnd_root = union.root("VGND")
    if vdpwr_root == vgnd_root:
        errors.append("VDPWR and VGND are electrically equivalent")
    label_roots: dict[str, list[str]] = defaultdict(list)
    for label in sorted(expected_labels):
        root = union.root(label)
        label_roots[root].append(label)
        if root in {vdpwr_root, vgnd_root}:
            errors.append(f"controller route {label} is shorted to a supply")
    aliased_labels = [labels for labels in label_roots.values() if len(labels) != 1]
    if aliased_labels:
        errors.append(f"controller route labels are mutually aliased: {aliased_labels[:4]}")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "exact assembled V3 controller-power GDS including frozen analog, 305 controller signals, all 18 row rails, and both 1.8 V supply nets",
        "errors": errors,
        "checks": {
            "magic_metrics": metrics,
            "extraction_warning_baseline_exact": warning_baseline_exact,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "power_overlay_nodes": sorted(overlay_nodes),
            "power_overlay_component_counts": {
                net: geometry["connectivity"][net]["connected_component_count"]
                for net in ("VDPWR", "VGND")
            },
            "power_overlay_orphan_vias": sum(
                len(geometry["connectivity"][net]["orphan_vias"])
                for net in ("VDPWR", "VGND")
            ),
            "row_rails": geometry["counts"]["rails"],
            "upper_contacts": geometry["counts"]["upper_contacts"],
            "analog_population": analog,
            "digital_population": digital,
            "total_extracted_devices": len(rows),
            "route_labels_in_flat_extraction": len(flat_labels),
            "distinct_route_label_groups": len(label_roots),
            "routes_shorted_to_supply": sum(
                union.root(label) in {vdpwr_root, vgnd_root}
                for label in expected_labels
            ),
            "vdpwr_and_vgnd_are_distinct": vdpwr_root != vgnd_root,
        },
        "artifact_sha256": {
            "gds": sha256(args.gds),
            "geometry": sha256(args.geometry),
            "precheck": sha256(args.precheck),
            "source_gate": sha256(args.source_gate),
            "magic_log": sha256(args.magic_log),
            "extraction_feedback": sha256(args.extraction_feedback),
            "flat_spice": sha256(args.flat_spice),
            "top_ext": sha256(args.top_ext),
            "overlay_ext": sha256(args.overlay_ext),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/control_power"
    readback = base / "magic_readback"
    parser.add_argument(
        "--gds", type=Path,
        default=base / "direct/v3_four_channel_ctrl_powered.gds",
    )
    parser.add_argument("--geometry", type=Path, default=base / "power_geometry.json")
    parser.add_argument(
        "--precheck", type=Path, default=base / "precheck/precheck_summary.json"
    )
    parser.add_argument(
        "--source-gate", type=Path,
        default=ROOT / "v3/evidence/physical_control_signal_routing_gate.json",
    )
    parser.add_argument(
        "--magic-log", type=Path, default=readback / "magic_readback.log"
    )
    parser.add_argument(
        "--extraction-feedback", type=Path,
        default=readback / "extraction_feedback.txt",
    )
    parser.add_argument(
        "--frozen-feedback", type=Path,
        default=ROOT / "v3/frozen/controller_signal_routing/extraction_feedback.txt",
    )
    parser.add_argument(
        "--flat-spice", type=Path,
        default=readback / "v3_four_channel_ctrl_powered_flat.spice",
    )
    parser.add_argument(
        "--top-ext", type=Path,
        default=readback / "v3_four_channel_ctrl_powered.ext",
    )
    parser.add_argument(
        "--overlay-ext", type=Path,
        default=readback / "v3_ctrl_power_routes.ext",
    )
    parser.add_argument("--report", type=Path, default=base / "power_topology_audit.json")
    args = parser.parse_args()
    report = validate(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
