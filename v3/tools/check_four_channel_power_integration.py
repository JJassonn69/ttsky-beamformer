#!/usr/bin/env python3
"""Audit the exact V3 shared-power GDS and its flattened extracted topology."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/v3/four_channel_power_integration"
DEFAULT_OUTPUT = ROOT / "v3/evidence/four_channel_power_integration_gate.json"
CHANNEL_PREFIX = (
    "v3_four_channel_output_load_integration_0/"
    "v3_four_channel_shared_support_integration_0/"
    "v3_four_channel_bias_reference_distribution_0/v3_four_channel_phase_distribution_0/"
    "v3_four_channel_output_collection_0/v3_four_channel_placement_0/"
    "v3_channel_selector_late_promotion_"
)
PHASE_PREFIX = (
    "v3_four_channel_output_load_integration_0/"
    "v3_four_channel_shared_support_integration_0/"
    "v3_four_channel_bias_reference_distribution_0/v3_four_channel_phase_distribution_0/"
)
OUTPUT_PREFIX = "v3_four_channel_output_load_integration_0/"
ISOLATED_INTERFACES = [
    "element_input",
    *(f"group{group}_bit{bit}" for group in range(4) for bit in range(2)),
    "channel_enable",
    "mixers_blank",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, default=BUILD / "v3_four_channel_power_integration.gds")
    parser.add_argument(
        "--spice", type=Path,
        default=BUILD / "readback/v3_four_channel_power_integration_flat.spice",
    )
    parser.add_argument("--magic-log", type=Path, default=BUILD / "magic_readback.log")
    parser.add_argument("--precheck", type=Path, default=BUILD / "precheck/precheck_summary.json")
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "v3/layout/four_channel_power_integration.json",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows: list[tuple[list[str], int]] = []
    nodes: set[str] = set()
    models = Counter()
    for line in args.spice.read_text(encoding="utf-8").splitlines():
        if not line.startswith("X"):
            continue
        row = line.split()
        model_index = next(index for index, value in enumerate(row) if value.startswith("sky130_"))
        rows.append((row, model_index))
        nodes.update(row[1:model_index])
        models[row[model_index]] += 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
    upstream = current["frozen_stage_inputs"]["four_channel_power_integration"]
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    log = args.magic_log.read_text(encoding="utf-8", errors="replace")

    exact_hits = {
        net: sum(row[1:model_index].count(net) for row, model_index in rows)
        for net in ("VDPWR", "VGND")
    }
    stale_power_nodes = sorted(
        node for node in nodes
        if node.endswith("/VPWR") or node.endswith("/VDPWR") or node.endswith("/VGND")
    )
    output_hits = {
        name: sum(row[1:model_index].count(OUTPUT_PREFIX + name) for row, model_index in rows)
        for name in ("combined_p", "combined_n")
    }
    ref_nodes = sorted(node for node in nodes if node.endswith("/ref"))
    vbias_nodes = sorted(node for node in nodes if node.endswith("/vbias"))
    ref_hits = sum(row[1:mi].count(ref_nodes[0]) for row, mi in rows) if len(ref_nodes) == 1 else 0
    vbias_hits = sum(row[1:mi].count(vbias_nodes[0]) for row, mi in rows) if len(vbias_nodes) == 1 else 0
    phase_hits = {
        name: sum(row[1:mi].count(PHASE_PREFIX + name) for row, mi in rows)
        for name in ("phase_0", "phase_90", "phase_180", "phase_270")
    }
    observed_isolated = {
        name: sorted(node for node in nodes if node.endswith("/" + name))
        for name in ISOLATED_INTERFACES
    }
    expected_isolated = {
        name: [f"{CHANNEL_PREFIX}{channel}/{name}" for channel in range(4)]
        for name in ISOLATED_INTERFACES
    }
    cross_channel_rows = []
    for row, _model_index in rows:
        found = sorted(set(re.findall(rf"{re.escape(CHANNEL_PREFIX)}([0-3])/", " ".join(row))))
        if len(found) > 1:
            cross_channel_rows.append(" ".join(row))
    unexpected_unprefixed = sorted(
        node for node in nodes if "/" not in node and node not in {"VDPWR", "VGND"}
    )
    ext_text = (BUILD / "readback/v3_four_channel_power_integration.ext").read_text(
        encoding="utf-8", errors="replace"
    )
    rail_equivalences = sorted(
        line for line in ext_text.splitlines()
        if line.startswith("equiv") and ("VDPWR" in line or "VGND" in line)
    )

    checks = {
        "source_is_exact_frozen_upstream_top": (
            manifest["source"]["gds"] == upstream["gds"]
            and manifest["source"]["gds_sha256"] == upstream["gds_sha256"]
            and sha256(ROOT / upstream["gds"]) == upstream["gds_sha256"]
        ),
        "gds_matches_precheck": precheck["gds_sha256"] == sha256(args.gds),
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "magic_drc_zero": marker(log, "V3_FOUR_CHANNEL_POWER_DRC_COUNT") == 0,
        "only_nine_qualified_dummy_feedback_markers": marker(
            log, "V3_FOUR_CHANNEL_POWER_EXTRACTION_FEEDBACK_COUNT"
        ) == 9,
        "device_population_is_exact": len(rows) == 1315,
        "model_population_is_exact": models == {
            "sky130_fd_pr__nfet_01v8": 880,
            "sky130_fd_pr__pfet_01v8_hvt": 416,
            "sky130_fd_pr__res_xhigh_po_0p35": 4,
            "sky130_fd_pr__res_xhigh_po_1p41": 6,
            "sky130_fd_pr__res_high_po_1p41": 3,
            "sky130_fd_pr__cap_mim_m3_1": 6,
        },
        "one_unified_vdpwr_reaches_every_expected_terminal": exact_hits["VDPWR"] == 740,
        "one_unified_vgnd_reaches_every_expected_terminal": exact_hits["VGND"] == 1360,
        "vdpwr_and_vgnd_are_not_equivalent": not rail_equivalences,
        "no_stale_hierarchical_power_nodes_remain": not stale_power_nodes,
        "output_topology_is_preserved": output_hits == {"combined_p": 122, "combined_n": 121},
        "ref_and_vbias_topology_is_preserved": ref_hits == 69 and vbias_hits == 79,
        "phase_trees_remain_exactly_32_terminals_each": set(phase_hits.values()) == {32},
        "control_and_input_interfaces_remain_isolated": observed_isolated == expected_isolated,
        "no_device_bridges_two_channel_namespaces": not cross_channel_rows,
        "no_unexpected_unprefixed_nodes": not unexpected_unprefixed,
        "uses_only_the_1v8_supply_domain": not manifest["constraints"]["uses_vapwr"],
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact shared VDPWR/VGND routing, rail isolation, and preserved four-channel topology",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "device_count": len(rows),
        "model_population": dict(sorted(models.items())),
        "power_terminal_hits": exact_hits,
        "stale_hierarchical_power_nodes": stale_power_nodes,
        "rail_equivalences": rail_equivalences,
        "output_terminal_hits": output_hits,
        "support_terminal_hits": {"ref": ref_hits, "vbias": vbias_hits},
        "phase_terminal_hits": phase_hits,
        "cross_channel_device_rows": cross_channel_rows,
        "unexpected_unprefixed_nodes": unexpected_unprefixed,
        "sha256": {
            "manifest": sha256(args.manifest),
            "flat_spice": sha256(args.spice),
            "magic_ext": sha256(BUILD / "readback/v3_four_channel_power_integration.ext"),
            "magic_log": sha256(args.magic_log),
            "precheck": sha256(args.precheck),
            "auditor": sha256(Path(__file__)),
        },
        "next_gate": "freeze shared power, then integrate static control and four analog-input pad escapes",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
