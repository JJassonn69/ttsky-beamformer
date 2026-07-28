import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "build/v2/postlayout_trim/base/summary.json"
GDS = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
BASE_NETLIST = ROOT / "build/v2/control_routing/final_rc/control_final_base.spice"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ControlPostlayoutTrimEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = json.loads(SUMMARY.read_text())

    def test_complete_sweep_is_bound_to_the_exact_candidate(self) -> None:
        self.assertEqual(self.summary["status"], "pass")
        self.assertEqual(self.summary["errors"], [])
        self.assertEqual(self.summary["case_count"], 64)
        self.assertEqual(self.summary["codes_per_channel"], 16)
        self.assertEqual(
            self.summary["artifact_hashes"]["gds_sha256"], [sha256(GDS)]
        )
        self.assertEqual(
            self.summary["artifact_hashes"]["netlist_sha256"],
            [sha256(BASE_NETLIST)],
        )

    def test_every_channel_has_useful_monotonic_trim_range(self) -> None:
        self.assertEqual(len(self.summary["trim_span_db_by_channel"]), 4)
        for span_db in self.summary["trim_span_db_by_channel"]:
            self.assertGreaterEqual(span_db, 1.5)
        for result in self.summary["monotonicity_by_channel"]:
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["inverted_steps_after_codes"], [])
        for result in self.summary["useful_resolution_by_channel"]:
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["under_resolved_steps_after_codes"], [])
            self.assertGreaterEqual(result["minimum_adjacent_step_db"], 0.03)

    def test_nominal_optimizer_preserves_already_matched_gain(self) -> None:
        calibration = self.summary["calibration"]
        self.assertEqual(calibration["codes_ch0_to_ch3"], [8, 8, 8, 8])
        self.assertEqual(calibration["maximum_absolute_gain_shift_from_default_db"], 0.0)
        self.assertLess(calibration["spread_db"], 0.01)
        self.assertEqual(calibration["total_code_distance_from_default"], 0)

    def test_injected_mismatch_is_corrected_without_monte_carlo_claim(self) -> None:
        stress = self.summary["injected_mismatch_stress"]
        self.assertIn("not foundry mismatch Monte Carlo", stress["method"])
        self.assertGreater(stress["untrimmed_code8_spread_db"], 1.1)
        self.assertLess(stress["calibration"]["spread_db"], 0.1)
        self.assertLessEqual(
            stress["calibration"]["maximum_absolute_gain_shift_from_default_db"],
            2.0,
        )

    def test_trim_does_not_disturb_shared_vcm(self) -> None:
        for channel_values in self.summary["vcm_v_by_channel_and_code"]:
            self.assertLess(max(channel_values) - min(channel_values), 0.0001)
            self.assertTrue(all(1.19 < value < 1.21 for value in channel_values))


if __name__ == "__main__":
    unittest.main()
