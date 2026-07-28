import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_placement import validate
from generate_control_placement import Placer
from map_control_netlist import lef_cell_spec


class ControlPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(
            (ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()
        )
        cls.placement = json.loads(
            (ROOT / "build/v2/control_placement/control_placement.json").read_text()
        )
        cls.integration = json.loads(
            (ROOT / "v2/layout/integration_plan.json").read_text()
        )
        cls.floorplan = json.loads((ROOT / "v2/layout/floorplan.json").read_text())

    def check(self, placement):
        return validate(self.mapping, placement, self.integration, self.floorplan)

    def test_production_candidate_passes(self) -> None:
        report = self.check(self.placement)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["mapped_standard_cells"], 194)
        self.assertGreater(report["fillers"], 0)
        self.assertEqual(report["unfilled_complete_site_count"], 0)
        self.assertEqual(report["overlap_count"], 0)
        self.assertGreaterEqual(report["minimum_trim_output_pitch_um"], 0.70)
        self.assertGreater(report["weighted_hpwl_improvement_fraction"], 0.20)
        self.assertGreater(
            report["orientation_optimization"]["improvement_fraction"], 0.01
        )
        self.assertLessEqual(
            max(max(rows.values()) for rows in report["row_signal_utilization"].values()),
            0.55,
        )
        self.assertEqual(
            report["phase_shift_chain"]["topology"],
            "channel_aligned_two_row_interleave",
        )
        self.assertLessEqual(
            report["phase_shift_chain"]["maximum_phase_bit_hpwl_um"], 21.0
        )
        self.assertLessEqual(report["phase_shift_chain"]["cfg_data_hpwl_um"], 60.0)
        self.assertEqual(report["paired_storage"]["enabled_d_net_count"], 58)
        self.assertEqual(report["paired_storage"]["static_trim_tradeoff_count"], 16)
        self.assertLessEqual(
            report["paired_storage"]["maximum_local_pair_hpwl_um"], 3.0
        )
        self.assertLessEqual(
            report["paired_storage"]["maximum_static_trim_enabled_hpwl_um"], 12.3
        )

    def test_phase_shift_stages_are_channel_aligned_and_interleaved(self) -> None:
        phase = {
            item["pin_access"]["Q"]["net"]: item
            for item in self.placement["placements"]
            if item["role"] == "phase_shift_storage"
        }
        bit_zero = phase["serial_phase_to_trim"]
        self.assertEqual(bit_zero["row"], 4)
        self.assertGreater(bit_zero["pin_access"]["Q"]["point_um"][0], 160.0)
        for index in range(1, 8):
            item = phase[f"phase_config/shift_bits[{index}]"]
            self.assertEqual(item["row"], 4 if index % 2 == 0 else 5)

    def test_generation_is_deterministic(self) -> None:
        tap = lef_cell_spec(
            ROOT / "third_party/sky130_fd_sc_hd_cells/sky130_fd_sc_hd__tapvpwrvgnd_1.lef"
        )
        generated = Placer(
            self.mapping, self.integration, self.floorplan, tap
        ).result()
        self.assertEqual(generated, self.placement)

    def test_off_grid_cell_is_rejected(self) -> None:
        placement = copy.deepcopy(self.placement)
        placement["placements"][0]["origin_um"][0] += 0.01
        self.assertEqual(self.check(placement)["status"], "fail")

    def test_missing_row_taps_are_rejected(self) -> None:
        placement = copy.deepcopy(self.placement)
        victim = placement["well_taps"][0]
        placement["well_taps"] = [
            tap for tap in placement["well_taps"]
            if not (tap["region"] == victim["region"] and tap["row"] == victim["row"])
        ]
        self.assertEqual(self.check(placement)["status"], "fail")

    def test_missing_filler_site_is_rejected(self) -> None:
        placement = copy.deepcopy(self.placement)
        placement["fillers"] = placement["fillers"][1:]
        self.assertEqual(self.check(placement)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
