#!/usr/bin/env python3
"""Bind the matched output loads and direct analog-pad escapes to frozen V3."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"
BLOCK_GDS = ROOT / "build/v3/output_load_pair_block/v3_output_load_pair_block.gds"
BLOCK_LOG = ROOT / "build/v3/output_load_pair_block/magic_build.log"
BLOCK_PRECHECK = ROOT / "build/v3/output_load_pair_block/precheck_summary.json"
CAP_GDS = ROOT / "build/v3/output_compensation_cap_block/v3_output_compensation_cap_block.gds"
CAP_LOG = ROOT / "build/v3/output_compensation_cap_block/magic_build.log"
CAP_PRECHECK = ROOT / "build/v3/output_compensation_cap_block/precheck/precheck_summary.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_output_load_integration.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_sha256(record: dict[str, Any]) -> str:
    """Hash only the immutable stage binding, not the evolving CURRENT file."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def marker(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def segment(start: list[float], stop: list[float], layer: str, width: float, net: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan output segment: {start} -> {stop}")
    return {"from": start, "to": stop, "layer": layer, "width_um": width, "net": net}


def build() -> dict[str, Any]:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    source = current["frozen_stage_inputs"]["four_channel_output_load_integration"]
    source_gds = ROOT / source["gds"]
    if sha256(source_gds) != source["gds_sha256"]:
        raise RuntimeError("CURRENT.json does not bind the exact frozen upstream four-channel source")

    precheck = json.loads(BLOCK_PRECHECK.read_text(encoding="utf-8"))
    log = BLOCK_LOG.read_text(encoding="utf-8", errors="replace")
    if precheck["status"] != "pass" or precheck["gds_sha256"] != sha256(BLOCK_GDS):
        raise RuntimeError("output-load block direct-GDS gate is stale")
    if marker(log, "V3_OUTPUT_LOAD_PAIR_DRC_COUNT") != 0:
        raise RuntimeError("output-load block Magic DRC gate is not closed")
    if marker(log, "V3_OUTPUT_LOAD_PAIR_EXTRACTION_FEEDBACK_COUNT") != 0:
        raise RuntimeError("output-load block extraction gate is not closed")

    cap_precheck = json.loads(CAP_PRECHECK.read_text(encoding="utf-8"))
    cap_log = CAP_LOG.read_text(encoding="utf-8", errors="replace")
    if cap_precheck["status"] != "pass" or cap_precheck["gds_sha256"] != sha256(CAP_GDS):
        raise RuntimeError("output compensation-capacitor direct-GDS gate is stale")
    if marker(cap_log, "V3_OUTPUT_COMP_CAP_DRC_COUNT") != 0:
        raise RuntimeError("output compensation-capacitor Magic DRC gate is not closed")
    if marker(cap_log, "V3_OUTPUT_COMP_CAP_EXTRACTION_FEEDBACK_COUNT") != 0:
        raise RuntimeError("output compensation-capacitor extraction gate is not closed")

    # The N pad is 24.12 um farther from its collector than P after including
    # the already-routed collector trees.  Keep the new segment at the proven
    # 0.4 um width until x=84 um, outside the H-tree corridor; only then widen
    # to 0.760/0.900 um.  This keeps every edge on the 5 nm manufacturing grid
    # and makes sum(length/width) differ by <0.3% while
    # respecting the 0.90 um analog-pin aperture.  Distributed-RC extraction
    # remains authoritative because capacitance is not proportional to L/W.
    widths = {"p": 0.760, "n": 0.900}
    roots = {"p": [116.37, 145.3], "n": [117.17, 147.3]}
    load_ports = {"p": [74.98, 115.29], "n": [55.66, 115.29]}
    tracks = {"p": 77.50, "n": 58.50}
    widening_x = 84.0
    pins = {"p": [74.98, 0.50], "n": [55.66, 0.50]}
    collector_lengths = {"p": 30.37, "n": 32.37}
    routes: dict[str, Any] = {}
    for polarity in ("p", "n"):
        root = roots[polarity]
        port = load_ports[polarity]
        track = tracks[polarity]
        width = widths[polarity]
        records = [
            segment(root, [widening_x, root[1]], "metal3", 0.4, f"combined_{polarity}"),
            segment([widening_x, root[1]], [track, root[1]], "metal3", width, f"combined_{polarity}"),
            segment([track, root[1]], [track, port[1]], "metal3", width, f"combined_{polarity}"),
            segment([track, port[1]], port, "metal3", width, f"combined_{polarity}"),
            segment(port, pins[polarity], "metal4", width, f"combined_{polarity}"),
        ]
        segment_lengths = [
            abs(record["to"][0] - record["from"][0])
            + abs(record["to"][1] - record["from"][1])
            for record in records
        ]
        escape_length = sum(segment_lengths)
        routes[polarity] = {
            "net": f"combined_{polarity}",
            "collector_root_um": root,
            "load_port_um": port,
            "analog_pin": "ua[4]" if polarity == "p" else "ua[5]",
            "analog_pin_um": pins[polarity],
            "width_um": width,
            "segments": records,
            "via2_points_um": [port],
            "via3_points_um": [port],
            "pad_size_um": [0.90, 1.00],
            "collector_source_to_root_length_um": collector_lengths[polarity],
            "root_to_pad_length_um": round(escape_length, 6),
            "first_order_sheet_resistance_metric": round(
                collector_lengths[polarity] / 0.4
                + sum(length / record["width_um"] for length, record in zip(segment_lengths, records)),
                6,
            ),
            "direction_reversals": 0,
        }

    metrics = [routes[p]["first_order_sheet_resistance_metric"] for p in ("p", "n")]
    mismatch = 200.0 * abs(metrics[0] - metrics[1]) / sum(metrics)
    return {
        "schema_version": 1,
        "status": "output-load integration candidate; exact GDS and distributed-RC checks pending",
        "units": "um",
        "top_cell": "v3_four_channel_output_load_integration",
        "source": {
            "gds": source["gds"],
            "gds_sha256": source["gds_sha256"],
            "top_cell": source["top_cell"],
            "current_manifest": str(CURRENT.relative_to(ROOT)),
            "stage_binding_sha256": record_sha256(source),
        },
        "output_load_block": {
            "gds": str(BLOCK_GDS.relative_to(ROOT)),
            "gds_sha256": sha256(BLOCK_GDS),
            "top_cell": "v3_output_load_pair_block",
            "translation_um": [0.0, 0.0],
            "bbox_um": [54.125, 114.285, 76.515, 131.715],
            "precheck": str(BLOCK_PRECHECK.relative_to(ROOT)),
            "precheck_sha256": sha256(BLOCK_PRECHECK),
            "magic_log": str(BLOCK_LOG.relative_to(ROOT)),
            "magic_log_sha256": sha256(BLOCK_LOG),
        },
        "compensation_cap_block": {
            "gds": str(CAP_GDS.relative_to(ROOT)),
            "gds_sha256": sha256(CAP_GDS),
            "top_cell": "v3_output_compensation_cap_block",
            "translation_um": [0.0, 0.0],
            "bbox_um": [61.82, 101.70, 68.18, 106.30],
            "size_um": [4.20, 4.20],
            "output_terminal_um": [64.12, 104.0],
            "ground_terminal_um": [67.92, 104.0],
            "precheck": str(CAP_PRECHECK.relative_to(ROOT)),
            "precheck_sha256": sha256(CAP_PRECHECK),
            "magic_log": str(CAP_LOG.relative_to(ROOT)),
            "magic_log_sha256": sha256(CAP_LOG),
            "typical_model_capacitance_ff": 38.03425,
            "typical_model_formula": "2.00*(w-0.025)*(l-0.025) + 0.19*2*((w-0.025)+(l-0.025)) fF",
        },
        "compensation_routes": {
            "combined_p": [
                segment([74.98, 99.0], [64.12, 99.0], "metal4", 0.50, "combined_p"),
                segment([64.12, 99.0], [64.12, 104.0], "metal4", 0.50, "combined_p"),
            ],
            "VGND": [
                segment([67.92, 104.0], [67.92, 85.0], "metal3", 0.80, "VGND"),
                segment([67.92, 85.0], [45.20, 85.0], "metal3", 0.80, "VGND"),
                segment([45.20, 85.0], [45.20, 78.0], "metal3", 0.80, "VGND"),
            ],
        },
        "routes": routes,
        "matching": {
            "method": "first-order series sheet-resistance compensation without meanders",
            "metric_definition": "collector_length/0.4 + sum(each escape segment length/its width)",
            "metric_mismatch_percent": round(mismatch, 6),
            "distributed_capacitance_matched": False,
            "distributed_rc_gate_required": True,
            "uncompensated_extracted_capacitance_ff": {"p": 301.51883, "n": 342.11402},
            "uncompensated_capacitance_mismatch_percent": 12.614393,
            "compensation_strategy": "one foundry MIM capacitor from combined_p to the existing VCM VGND trunk; exact size tuned by re-extraction",
        },
        "routing_decisions": {
            "load_placement": "west-side clear corridor; the old nominal load box is occupied by the final channel macro",
            "metal3": "direct collector-to-load paths stay outside load resistor bodies",
            "metal4": "one straight drop from each load terminal to its analog pin",
            "no_meanders": True,
            "no_u_turns": True,
            "no_floating_stubs": True,
            "no_orphan_vias": True,
            "compensation_ground": "M3 dogleg below the REF crossing into the existing VCM VGND trunk",
            "compensation_top_plate": "M4 approaches C1 vertically from below the capacitor bbox and never crosses the C2 Via-3 strip",
        },
        "constraints": {
            "source_is_exact_frozen_stage_input": True,
            "load_block_is_exact_hash_bound": True,
            "compensation_cap_block_is_exact_hash_bound": True,
            "maximum_direction_reversals": 0,
            "analog_pin_max_width_um": 0.90,
            "first_order_resistance_mismatch_limit_percent": 1.0,
            "full_rc_mismatch_limit_percent": 1.0,
            "frozen_source_geometry_modified": False,
            "gds_timestamps_canonicalized": True,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_output_load_integration.py",
            "generator_sha256": sha256(Path(__file__)),
            "composer": "v3/tools/compose_four_channel_output_load_integration.py",
            "composer_sha256": sha256(ROOT / "v3/tools/compose_four_channel_output_load_integration.py"),
        },
    }


def main() -> None:
    DEFAULT_OUTPUT.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
