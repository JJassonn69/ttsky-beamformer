#!/usr/bin/env python3
"""Audit four-channel abutment, device replication, and signal isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/four_channel_placement"
DEFAULT_OUTPUT = ROOT / "v3/evidence/four_channel_placement_gate.json"
PREFIX = "v3_channel_selector_late_promotion_"
ISOLATED_INTERFACES = [
    "element_input", "ref", "vbias", "row_outp", "row_outn",
    "phase_0", "phase_90", "phase_180", "phase_270",
    *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    "channel_enable", "mixers_blank", "VPWR",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def parse(path: Path) -> tuple[list[list[str]], set[str]]:
    rows = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("X")]
    nodes: set[str] = set()
    for row in rows:
        model_index = next(index for index, value in enumerate(row) if value.startswith("sky130_"))
        nodes.update(row[1:model_index])
    return rows, nodes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_placement.gds")
    parser.add_argument("--spice", type=Path, default=BUILD / "readback/v3_four_channel_placement_flat.spice")
    parser.add_argument("--magic-log", type=Path, default=BUILD / "magic_readback.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck_summary.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "v3/layout/four_channel_placement.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows, nodes = parse(args.spice)
    log = args.magic_log.read_text(encoding="utf-8", errors="replace")
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    models = Counter(
        next(value for value in row if value.startswith("sky130_")) for row in rows
    )
    channel_rows: dict[str, int] = {}
    cross_channel_rows: list[str] = []
    for channel in range(4):
        prefix = f"{PREFIX}{channel}/"
        channel_rows[str(channel)] = sum(prefix in " ".join(row) for row in rows)
    for row in rows:
        found = sorted(set(re.findall(rf"{re.escape(PREFIX)}([0-3])/", " ".join(row))))
        if len(found) > 1:
            cross_channel_rows.append(" ".join(row))

    interface_nodes: dict[str, list[str]] = {}
    expected_interface_nodes: dict[str, list[str]] = {}
    for name in ISOLATED_INTERFACES:
        interface_nodes[name] = sorted(node for node in nodes if node.endswith("/" + name))
        expected_interface_nodes[name] = [f"{PREFIX}{channel}/{name}" for channel in range(4)]
    unexpected_unprefixed = sorted(
        node for node in nodes
        if node != "VSUBS" and not node.startswith(PREFIX)
    )

    checks = {
        "manifest_uses_exact_frozen_macro": (
            manifest["frozen_macro"]["gds_sha256"]
            == json.loads((ROOT / "v3/CURRENT.json").read_text())["gds_sha256"]
        ),
        "gds_matches_precheck": precheck["gds_sha256"] == sha256(args.gds),
        "direct_gds_precheck_zero": (
            precheck["status"] == "pass"
            and all(item["markers"] == 0 for item in precheck["checks"].values())
        ),
        "magic_drc_zero": marker(log, "V3_FOUR_CHANNEL_PLACEMENT_DRC_COUNT") == 0,
        "only_nine_hierarchical_dummy_feedback_markers": (
            marker(log, "V3_FOUR_CHANNEL_PLACEMENT_EXTRACTION_FEEDBACK_COUNT") == 9
        ),
        "four_complete_channel_device_sets": len(rows) == 1292,
        "expected_model_population": models == {
            "sky130_fd_pr__nfet_01v8": 872,
            "sky130_fd_pr__pfet_01v8_hvt": 416,
            "sky130_fd_pr__res_xhigh_po_0p35": 4,
        },
        "equal_non_dummy_device_population_per_channel": set(channel_rows.values()) == {314},
        "thirty_six_grounded_dummies_share_only_substrate": (
            sum(PREFIX not in " ".join(row) for row in rows) == 36
            and all(set(row[1:5]) == {"VSUBS"} for row in rows if PREFIX not in " ".join(row))
        ),
        "no_device_bridges_two_channel_namespaces": not cross_channel_rows,
        "all_unrouted_signal_interfaces_remain_isolated": all(
            interface_nodes[name] == expected_interface_nodes[name]
            for name in ISOLATED_INTERFACES
        ),
        "no_unexpected_unprefixed_signal_nodes": not unexpected_unprefixed,
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "four immutable R0 channel copies: exact abutment geometry, replicated devices, and pre-routing signal isolation",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "device_count": len(rows),
        "models": dict(sorted(models.items())),
        "non_dummy_device_rows_per_channel": channel_rows,
        "global_grounded_dummy_rows": sum(PREFIX not in " ".join(row) for row in rows),
        "interface_nodes": interface_nodes,
        "cross_channel_device_rows": cross_channel_rows,
        "unexpected_unprefixed_signal_nodes": unexpected_unprefixed,
        "sha256": {
            "manifest": sha256(args.manifest),
            "flat_spice": sha256(args.spice),
            "magic_log": sha256(args.magic_log),
            "precheck": sha256(args.precheck),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "reserve and close the differential output collector before phase, bias, power, input, or control routing",
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
