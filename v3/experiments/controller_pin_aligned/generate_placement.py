#!/usr/bin/env python3
"""Generate V3 Candidate B with a pin-ordered controller ingress row."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "v3/tools"))

from generate_physical_control_placement import (  # noqa: E402
    CONFIG_X0,
    GLOBAL_X1,
    SITE,
    V3ControllerPlacer,
    row_orientation,
    sha256,
    snap_site,
)


OFFICIAL_PIN_ORDER = [
    "cfg_latch",
    "cfg_data",
    "cfg_clk",
    "channel_enable[3]",
    "channel_enable[2]",
    "channel_enable[1]",
    "channel_enable[0]",
    "raw_mode",
    "beam_select[2]",
    "beam_select[1]",
    "beam_select[0]",
    "rst_n",
    "clk",
    "ena",
]


class PinAlignedControllerPlacer(V3ControllerPlacer):
    """Keep Candidate A's footprint but make its north ingress intentional."""

    def _fanout_instances(self, net: str) -> list[str]:
        result = [
            cell["instance"]
            for cell in self.cells.values()
            if cell["pins"].get("A") == net
            and cell["instance"].startswith(f"physical_fanout/{net}/")
        ]
        return sorted(result)

    def _place_linear_bank(
        self,
        instances: list[str],
        start_x: float,
        row: int,
        region: str,
        rationale: str,
    ) -> float:
        x = snap_site(start_x)
        for index, instance in enumerate(instances):
            self.add(
                instance,
                x,
                row,
                row_orientation(row, bool(index % 2)),
                rationale,
                region,
                True,
            )
            x = snap_site(x + float(self.cells[instance]["size_um"][0]) + SITE)
        return x

    def place_input_synchronizers(self) -> None:
        # The wide direct-input flops remain in three short, vertically paired
        # banks.  Their ordering now follows the physical pin progression near
        # each bank instead of the logical bit number.
        sync_nets = {
            0: "direct_sync[0]",
            1: "beam_sync[0]",
            2: "beam_sync[1]",
            3: "beam_sync[2]",
            4: "direct_sync[4]",
            5: "channel_enable_sync[0]",
            6: "channel_enable_sync[1]",
            7: "channel_enable_sync[2]",
            8: "channel_enable_sync[3]",
        }
        bands = [
            ((5, 4, 3), 16, 15),
            ((8, 7, 6), 14, 13),
            ((2, 1, 0), 12, 11),
        ]
        for bits, meta_row, sync_row in bands:
            for slot, bit in enumerate(bits):
                x = 210.68 + slot * 9.66
                meta = self.q_cell(f"direct_meta[{bit}]")
                sync = self.q_cell(sync_nets[bit])
                self.add(
                    meta["instance"],
                    x,
                    meta_row,
                    row_orientation(meta_row),
                    f"Candidate B pin-ordered first synchronizer stage for direct bit {bit}",
                    "global_control_core",
                    True,
                )
                self.add(
                    sync["instance"],
                    x,
                    sync_row,
                    row_orientation(sync_row),
                    f"Candidate B second synchronizer stage aligned below direct bit {bit}",
                    "global_control_core",
                    True,
                )

        # Configuration fanout enters beside the compact left-hand local port
        # bank.  Main reset/clock fanout uses the otherwise empty row above the
        # configuration bank.  This removes random residual placement of the
        # eighteen switching ingress buffers without moving analog geometry.
        config_fanout = self._fanout_instances("cfg_latch")
        config_fanout += self._fanout_instances("cfg_clk")
        self._place_linear_bank(
            config_fanout,
            181.24,
            16,
            "global_control_core",
            "Candidate B northwest ordered configuration ingress fanout",
        )
        main_fanout = self._fanout_instances("rst_n")
        main_fanout += self._fanout_instances("clk")
        end_x = self._place_linear_bank(
            main_fanout,
            CONFIG_X0,
            16,
            "config_storage_bank",
            "Candidate B northeast ordered reset/clock ingress fanout",
        )
        if end_x > 284.30:
            raise ValueError(f"Candidate B ingress bank unexpectedly ends at {end_x:.3f} um")

    def result(self) -> dict[str, Any]:
        result = super().result()
        # Six M2 tracks equal one official TinyTapeout pin pitch (2.76 um).
        # Local pins preserve the official left-to-right order with a constant
        # translation; top-level routes therefore never need to permute nets.
        # Start on track index 1 rather than 2 so the clk port clears the
        # reserved top-row VDPWR landing at x=215.66 um by a full rule margin.
        x_values = [round(181.93 + 2.76 * index, 6) for index in range(14)]
        result["status"] = "Candidate B pre-route pin-aligned placement"
        result["candidate"] = "B"
        result["boundary_interface"] = {
            "edge": "north",
            "layer": "met2",
            "official_pin_order_left_to_right": OFFICIAL_PIN_ORDER,
            "local_pin_x_um": dict(zip(OFFICIAL_PIN_ORDER, x_values)),
            "local_pitch_um": 2.76,
            "track_pitch_um": 0.46,
            "policy": {
                "order_matches_fixed_tinytapeout_pins": True,
                "constant_pitch": True,
                "candidate_a_controller_bbox_preserved": True,
                "analog_geometry_unchanged": True,
            },
        }
        result["policy"]["candidate_a_submission_immutable"] = True
        result["policy"]["boundary_ingress_pin_aligned"] = True
        result["routing_intent"]["north_boundary"] = (
            "compact port bank in exact fixed-pin order; no top-level net permutation"
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping",
        type=Path,
        nargs="?",
        default=ROOT / "build/v3/control_mapping/physical_mapping.json",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=ROOT
        / "build/v3/experiments/controller_pin_aligned/physical_control_placement.json",
    )
    args = parser.parse_args()
    placement = PinAlignedControllerPlacer(
        json.loads(args.mapping.read_text(encoding="utf-8"))
    ).result()
    placement["provenance"] = {
        "mapping": str(args.mapping),
        "mapping_sha256": sha256(args.mapping),
        "generator": str(Path(__file__).relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__)),
        "candidate_a_manifest": (
            "v3/experiments/controller_pin_aligned/candidate_a_manifest.json"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(placement, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(args.output), **placement["counts"], **placement["metrics"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
