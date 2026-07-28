import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from check_physical_control_placement import validate
from generate_physical_control_placement import V3ControllerPlacer


class PhysicalControlPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(
            (ROOT / "build/v3/control_mapping/physical_mapping.json").read_text()
        )
        cls.placement = json.loads(
            (ROOT / "build/v3/control_placement/physical_control_placement.json").read_text()
        )

    def test_candidate_passes_contract(self) -> None:
        report = validate(self.mapping, self.placement)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["placed_standard_cells"], 291)
        self.assertEqual(report["overlap_count"], 0)
        self.assertEqual(report["uncovered_complete_site_count"], 0)
        self.assertLessEqual(report["maximum_tap_gap_um"], 13.80 + 1e-6)
        self.assertLessEqual(report["maximum_global_row_utilization"], 0.76)
        self.assertLessEqual(report["maximum_configuration_row_utilization"], 0.74)

    def test_high_fanout_nets_use_bounded_foundry_buffer_trees(self) -> None:
        trees = self.mapping["fanout_buffer_trees"]
        self.assertEqual(
            {item["root_net"] for item in trees},
            {"active_raw_mode", "apply_config", "cfg_clk", "cfg_latch", "clk", "rst_n"},
        )
        self.assertEqual(sum(item["branch_count"] for item in trees), 24)
        self.assertTrue(
            all(max(item["branch_loads"]) <= 16 for item in trees)
        )
        buffers = [
            item for item in self.mapping["cells"]
            if item["role"] == "fanout_buffer"
        ]
        self.assertEqual(len(buffers), 24)
        self.assertTrue(all(item["cell"] == "sky130_fd_sc_hd__buf_4" for item in buffers))

    def test_generation_is_deterministic(self) -> None:
        generated = V3ControllerPlacer(self.mapping).result()
        expected = copy.deepcopy(self.placement)
        expected.pop("provenance", None)
        self.assertEqual(generated, expected)

    def test_off_grid_cell_is_rejected(self) -> None:
        changed = copy.deepcopy(self.placement)
        changed["placements"][0]["origin_um"][0] += 0.01
        self.assertEqual(validate(self.mapping, changed)["status"], "fail")

    def test_missing_filler_is_rejected(self) -> None:
        changed = copy.deepcopy(self.placement)
        changed["fillers"] = changed["fillers"][1:]
        self.assertEqual(validate(self.mapping, changed)["status"], "fail")

    def test_missing_mapped_cell_is_rejected(self) -> None:
        changed = copy.deepcopy(self.placement)
        changed["placements"] = changed["placements"][1:]
        self.assertEqual(validate(self.mapping, changed)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
