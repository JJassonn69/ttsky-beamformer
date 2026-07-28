#!/usr/bin/env python3
"""Build the deterministic shared VDPWR/VGND routing manifest for V3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"
DEFAULT_OUTPUT = ROOT / "v3/layout/four_channel_power_integration.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_sha256(record: dict[str, Any]) -> str:
    """Hash only the immutable stage binding, not the evolving CURRENT file."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def segment(net: str, layer: str, start: list[float], stop: list[float], width: float, role: str) -> dict[str, Any]:
    if start[0] != stop[0] and start[1] != stop[1]:
        raise ValueError(f"non-Manhattan power segment: {start} -> {stop}")
    return {
        "net": net,
        "layer": layer,
        "from": start,
        "to": stop,
        "width_um": width,
        "role": role,
    }


def build() -> dict[str, Any]:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    source = current["frozen_stage_inputs"]["four_channel_power_integration"]
    source_path = ROOT / source["gds"]
    if sha256(source_path) != source["gds_sha256"]:
        raise RuntimeError("CURRENT.json does not bind the exact frozen output-integrated source")

    channel_vpwr = [[84.11, 187.45], [103.43, 187.45], [122.75, 187.45], [142.07, 187.45]]
    channel_vgnd = [[86.67, 184.73], [105.99, 184.73], [125.31, 184.73], [144.63, 184.73]]
    vdpwr_segments = [
        segment("VDPWR", "metal3", [2.0, 212.0], [8.0, 212.0], 1.20, "source_bridge_beneath_vgnd"),
        segment("VDPWR", "metal4", [8.0, 212.0], [272.0, 212.0], 1.20, "main_top_trunk"),
        # Keep this spine on M3.  A Metal-4 spine here would cross and short
        # the orthogonal VGND Metal-4 trunk at y=208 um even though both
        # individual routes are DRC-clean.
        segment("VDPWR", "metal3", [8.0, 145.0], [8.0, 212.0], 1.20, "west_distribution_spine_beneath_vgnd"),
        segment("VDPWR", "metal3", [8.0, 145.0], [50.0, 145.0], 0.80, "passive_supply_branch_west"),
        segment("VDPWR", "metal4", [50.0, 145.0], [61.0, 145.0], 0.80, "passive_supply_crossover"),
        segment("VDPWR", "metal3", [61.0, 145.0], [65.32, 145.0], 0.80, "passive_supply_branch_east"),
        segment("VDPWR", "metal2", [32.5, 140.845], [32.5, 145.0], 0.80, "vcm_supply_escape_below_existing_m3"),
        segment("VDPWR", "metal3", [65.32, 145.0], [65.32, 130.71], 0.80, "output_load_supply_drop"),
        segment("VDPWR", "metal4", [210.0, 104.395], [272.0, 104.395], 0.80, "tail_supply_exit"),
        segment("VDPWR", "metal4", [272.0, 104.395], [272.0, 212.0], 1.20, "east_distribution_spine"),
        segment("VDPWR", "metal4", [84.11, 187.45], [174.0, 187.45], 0.80, "four_channel_vpwr_bus"),
        segment("VDPWR", "metal3", [174.0, 187.45], [174.0, 212.0], 0.80, "channel_vpwr_spine"),
    ]

    vgnd_segments = [
        segment("VGND", "metal4", [5.0, 5.0], [15.0, 5.0], 0.80, "vcm_ground_to_external_source"),
        segment("VGND", "metal4", [5.0, 208.0], [267.82, 208.0], 1.20, "main_top_trunk"),
        segment("VGND", "metal3", [267.82, 30.0], [267.82, 208.0], 1.20, "tail_and_control_ground_spine"),
        segment("VGND", "metal4", [86.67, 184.73], [102.50, 184.73], 0.80, "channel_vgnd_bus_0"),
        segment("VGND", "metal3", [102.50, 184.73], [105.99, 184.73], 0.80, "vpwr_strap_crossover_0"),
        segment("VGND", "metal4", [105.99, 184.73], [121.80, 184.73], 0.80, "channel_vgnd_bus_1"),
        segment("VGND", "metal3", [121.80, 184.73], [125.31, 184.73], 0.80, "vpwr_strap_crossover_1"),
        segment("VGND", "metal4", [125.31, 184.73], [141.10, 184.73], 0.80, "channel_vgnd_bus_2"),
        segment("VGND", "metal3", [141.10, 184.73], [144.63, 184.73], 0.80, "vpwr_strap_crossover_2"),
        segment("VGND", "metal4", [144.63, 184.73], [170.0, 184.73], 0.80, "channel_vgnd_bus_3"),
        segment("VGND", "metal3", [170.0, 184.73], [170.0, 208.0], 0.80, "channel_vgnd_spine"),
    ]

    return {
        "schema_version": 1,
        "status": "shared-power integration candidate; exact DRC and extraction pending",
        "units": "um",
        "top_cell": "v3_four_channel_power_integration",
        "source": {
            **source,
            "current_manifest": str(CURRENT.relative_to(ROOT)),
            "stage_binding_sha256": record_sha256(source),
        },
        "external_power_pins": {
            "VDPWR": {"layer": "metal4", "bbox_um": [1.0, 5.0, 3.0, 220.76], "label_at_um": [2.0, 112.88]},
            "VGND": {"layer": "metal4", "bbox_um": [4.0, 5.0, 6.0, 220.76], "label_at_um": [5.0, 112.88]},
        },
        "endpoints": {
            "VDPWR": {
                "channels": [{"channel": index, "at_um": point, "layer": "metal4"} for index, point in enumerate(channel_vpwr)],
                "vcm": {"at_um": [32.5, 140.845], "layer": "metal2"},
                "output_load_pair": {"at_um": [65.32, 130.71], "layer": "metal2"},
                "tail_bias": {"at_um": [210.0, 104.395], "layer": "metal2"},
            },
            "VGND": {
                "channels": [{"channel": index, "at_um": point, "layer": "metal4"} for index, point in enumerate(channel_vgnd)],
                "vcm_and_compensation": {"at_um": [15.0, 5.0], "layer": "metal4"},
                "tail_bias": {"at_um": [267.82, 30.0], "layer": "metal4"},
            },
        },
        "routes": {"VDPWR": vdpwr_segments, "VGND": vgnd_segments},
        "via2_points_um": {
            "VDPWR": [[32.5, 145.0], [65.32, 130.71], [210.0, 104.395]],
            "VGND": [],
        },
        "via3_points_um": {
            "VDPWR": [
                [2.0, 212.0], [8.0, 212.0], [50.0, 145.0], [61.0, 145.0],
                [210.0, 104.395], [174.0, 187.45], [174.0, 212.0],
            ],
            "VGND": [
                [267.82, 30.0], [267.82, 208.0],
                [102.50, 184.73], [105.99, 184.73],
                [121.80, 184.73], [125.31, 184.73],
                [141.10, 184.73], [144.63, 184.73],
                [170.0, 184.73], [170.0, 208.0],
            ],
        },
        "routing_decisions": {
            "source_crossing": "VDPWR crosses beneath the full-height VGND Metal-4 stripe and the orthogonal VGND top trunk only on Metal 3",
            "passive_branch": "VCM escapes its terminal on Metal 2, then the shared branch promotes to Metal 4 only while crossing the REF and N-output Metal-3 trunks",
            "top_trunks": "separate 1.20 um Metal-4 trunks above all four phase trees",
            "channel_power": "one straight VPWR Metal-4 bus touches all four collinear ports; the VGND bus uses three short Metal-3 crossovers beneath the intervening vertical VPWR straps, then each rail exits beside the array on its own Metal-3 spine",
            "future_control_power": "east VDPWR/VGND spines are reserved as the supply boundary for the centralized control block",
            "no_signal_meanders": True,
            "no_floating_stubs": True,
            "no_orphan_vias": True,
        },
        "constraints": {
            "source_is_exact_frozen_stage_input": True,
            "supply_voltage_v": 1.8,
            "uses_vapwr": False,
            "main_trunk_width_um": 1.20,
            "branch_width_um": 0.80,
            "metal5_forbidden": True,
            "frozen_source_geometry_modified": False,
            "gds_timestamps_canonicalized": True,
        },
        "provenance": {
            "generator": "v3/tools/build_four_channel_power_integration.py",
            "generator_sha256": sha256(Path(__file__)),
            "composer": "v3/tools/compose_four_channel_power_integration.py",
            "composer_sha256": sha256(ROOT / "v3/tools/compose_four_channel_power_integration.py"),
        },
    }


def main() -> None:
    DEFAULT_OUTPUT.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(DEFAULT_OUTPUT)


if __name__ == "__main__":
    main()
