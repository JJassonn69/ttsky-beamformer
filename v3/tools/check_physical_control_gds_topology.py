#!/usr/bin/env python3
"""Close full-GDS connectivity for the V3 controller signal-route checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
ROUTE_LABEL_RE = re.compile(r"(?<![A-Za-z0-9_])V3R\d{3}(?![A-Za-z0-9_])")
MERGE_RE = re.compile(r'^merge "([^"]+)" "([^"]+)"')
MAGIC_METRIC_RE = {
    "gds_feedback": re.compile(r"V3_CONTROL_SIGNAL_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_CONTROL_SIGNAL_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(
        r"V3_CONTROL_SIGNAL_EXTRACTION_FEEDBACK_COUNT=(\d+)"
    ),
    "feedback_after_clear": re.compile(
        r"V3_CONTROL_SIGNAL_FEEDBACK_AFTER_CLEAR=(\d+)"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def root(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first: str, second: str) -> None:
        a, b = self.root(first), self.root(second)
        if a != b:
            self.parent[b] = a

    def groups(self) -> Iterable[set[str]]:
        grouped: dict[str, set[str]] = defaultdict(set)
        for item in self.parent:
            grouped[self.root(item)].add(item)
        return grouped.values()


def expected_digital_devices(mapping: dict[str, object]) -> tuple[int, dict[str, int]]:
    cells = mapping["cells"]
    counts = Counter(item["cell"] for item in cells)
    by_cell: dict[str, int] = {}
    total = 0
    for cell, count in sorted(counts.items()):
        spice = ROOT / "third_party/sky130_fd_sc_hd_cells" / f"{cell}.spice"
        devices = sum(
            line.startswith("X") for line in spice.read_text(encoding="utf-8").splitlines()
        )
        by_cell[cell] = count * devices
        total += count * devices
    return total, by_cell


def validate(
    gds: Path,
    geometry_path: Path,
    mapping_path: Path,
    route_audit_path: Path,
    magic_log: Path,
    extraction_feedback: Path,
    frozen_feedback: Path,
    flat_spice: Path,
    top_ext: Path,
    overlay_ext: Path,
) -> dict[str, object]:
    errors: list[str] = []
    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    route_audit = json.loads(route_audit_path.read_text(encoding="utf-8"))
    expected_labels = set(geometry["label_net_map"])
    if expected_labels != {f"V3R{index:03d}" for index in range(305)}:
        errors.append("route geometry label set is not exactly V3R000:V3R304")
    if route_audit.get("status") != "pass" or route_audit.get("errors"):
        errors.append("source detailed route did not pass its graph audit")

    log_text = magic_log.read_text(encoding="utf-8")
    metrics: dict[str, int | None] = {}
    for name, pattern in MAGIC_METRIC_RE.items():
        matches = [int(value) for value in pattern.findall(log_text)]
        metrics[name] = matches[-1] if matches else None
    if metrics["gds_feedback"] != 0:
        errors.append("Magic GDS import feedback is not zero")
    if metrics["drc"] != 0:
        errors.append("Magic DRC count is not zero")
    if metrics["feedback_after_clear"] != 0:
        errors.append("Magic feedback did not clear after recording extraction warnings")
    if metrics["extraction_feedback"] != 9:
        errors.append("Magic extraction warning count differs from the frozen nine-marker baseline")
    if extraction_feedback.read_bytes() != frozen_feedback.read_bytes():
        errors.append("extraction warnings differ from the frozen analog baseline")

    flat_lines = flat_spice.read_text(encoding="utf-8").splitlines()
    flat_labels = {
        match.group(0)
        for line in flat_lines
        for match in ROUTE_LABEL_RE.finditer(line)
    }
    if flat_labels != expected_labels:
        errors.append(
            "flattened extraction loses or aliases route labels: "
            f"missing={sorted(expected_labels - flat_labels)}, "
            f"unexpected={sorted(flat_labels - expected_labels)}"
        )
    device_lines = [line for line in flat_lines if line.startswith("X")]
    incidence = Counter()
    for line in device_lines:
        incidence.update(set(ROUTE_LABEL_RE.findall(line)))
    missing_device_incidence = sorted(expected_labels - set(incidence))
    if missing_device_incidence:
        errors.append(
            f"route labels absent from extracted device terminals: {missing_device_incidence}"
        )

    digital_devices, digital_by_cell = expected_digital_devices(mapping)
    analog_devices = 1315
    expected_devices = analog_devices + digital_devices
    if len(device_lines) != expected_devices:
        errors.append(
            f"extracted device count {len(device_lines)} != expected {expected_devices}"
        )

    overlay_text = overlay_ext.read_text(encoding="utf-8")
    overlay_nodes = {
        match.group(1)
        for match in re.finditer(r'^node "(V3R\d{3})"', overlay_text, re.MULTILINE)
    }
    if overlay_nodes != expected_labels:
        errors.append("route-overlay extraction does not preserve all 305 route nodes")

    uf = UnionFind()
    for line in top_ext.read_text(encoding="utf-8").splitlines():
        match = MERGE_RE.match(line)
        if match:
            uf.union(match.group(1), match.group(2))
    route_groups: list[dict[str, object]] = []
    forbidden_fragments = (
        "/VGND", "/VNB", "/VPWR", "/VPB",
        "v3_four_channel_", "v3_channel_", "v3_selector_",
        "v3_tail_", "v3_output_", "v3_vcm_",
    )
    for group in uf.groups():
        labels = sorted({label for item in group for label in ROUTE_LABEL_RE.findall(item)})
        if not labels:
            continue
        power_or_analog = sorted(
            item for item in group
            if item in {"VGND", "VDPWR", "VPWR"}
            or any(fragment in item for fragment in forbidden_fragments)
        )
        if len(labels) != 1:
            errors.append(f"full-GDS extraction aliases route labels {labels}")
        if power_or_analog:
            errors.append(
                f"{labels[0]} touches frozen analog/power nodes {power_or_analog[:8]}"
            )
        route_groups.append({
            "labels": labels,
            "merged_node_count": len(group),
            "power_or_analog_node_count": len(power_or_analog),
        })

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "exact assembled GDS after frozen analog/power geometry and controller routes are combined",
        "checks": {
            "magic_metrics": metrics,
            "route_labels_expected": len(expected_labels),
            "route_labels_in_flat_extraction": len(flat_labels),
            "route_labels_with_device_incidence": len(incidence),
            "minimum_device_line_incidence": min(incidence.values(), default=0),
            "route_overlay_extracted_nodes": len(overlay_nodes),
            "route_merge_groups": len(route_groups),
            "extracted_devices": len(device_lines),
            "expected_analog_devices": analog_devices,
            "expected_digital_devices": digital_devices,
            "expected_total_devices": expected_devices,
            "digital_devices_by_cell": digital_by_cell,
            "extraction_warning_baseline_exact": (
                extraction_feedback.read_bytes() == frozen_feedback.read_bytes()
            ),
        },
        "artifact_sha256": {
            "gds": sha256(gds),
            "route_geometry": sha256(geometry_path),
            "mapping": sha256(mapping_path),
            "route_audit": sha256(route_audit_path),
            "magic_log": sha256(magic_log),
            "extraction_feedback": sha256(extraction_feedback),
            "flat_spice": sha256(flat_spice),
            "top_ext": sha256(top_ext),
            "overlay_ext": sha256(overlay_ext),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/control_routing/openroad_internal"
    readback = base / "magic_readback"
    parser.add_argument(
        "--gds", type=Path,
        default=base / "direct/v3_four_channel_control_signal_routed.gds",
    )
    parser.add_argument("--geometry", type=Path, default=base / "route_geometry.json")
    parser.add_argument(
        "--mapping", type=Path,
        default=ROOT / "build/v3/control_mapping/physical_mapping.json",
    )
    parser.add_argument("--route-audit", type=Path, default=base / "route_audit.json")
    parser.add_argument("--magic-log", type=Path, default=base / "magic_readback.log")
    parser.add_argument(
        "--extraction-feedback", type=Path,
        default=readback / "extraction_feedback.txt",
    )
    parser.add_argument(
        "--frozen-feedback", type=Path,
        default=ROOT / "build/v3/four_channel_power_integration/extraction_feedback.txt",
    )
    parser.add_argument(
        "--flat-spice", type=Path,
        default=readback / "v3_four_channel_ctrl_sig_routed_flat.spice",
    )
    parser.add_argument(
        "--top-ext", type=Path,
        default=readback / "v3_four_channel_ctrl_sig_routed.ext",
    )
    parser.add_argument(
        "--overlay-ext", type=Path,
        default=readback / "v3_ctrl_signal_routes.ext",
    )
    parser.add_argument(
        "--report", type=Path,
        default=base / "gds_topology_audit.json",
    )
    args = parser.parse_args()
    report = validate(
        args.gds,
        args.geometry,
        args.mapping,
        args.route_audit,
        args.magic_log,
        args.extraction_feedback,
        args.frozen_feedback,
        args.flat_spice,
        args.top_ext,
        args.overlay_ext,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "errors": report["errors"],
        "checks": report["checks"],
    }, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
