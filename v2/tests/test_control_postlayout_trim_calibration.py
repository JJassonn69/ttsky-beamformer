import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_trim_calibration import (
    choose_calibration,
    case_report_path,
    codes_for_case,
    injected_mismatch_stress,
    monotonicity,
    run_case,
    spread_db,
    useful_resolution,
)


class ControlPostlayoutTrimCalibrationTests(unittest.TestCase):
    def test_only_the_selected_channel_code_changes(self) -> None:
        self.assertEqual(codes_for_case(0, 3), (3, 8, 8, 8))
        self.assertEqual(codes_for_case(3, 15), (8, 8, 8, 15))

    def test_calibration_reduces_deterministic_channel_spread(self) -> None:
        responses = [
            [0.80 + 0.02 * code for code in range(16)],
            [0.84 + 0.02 * code for code in range(16)],
            [0.88 + 0.02 * code for code in range(16)],
            [0.92 + 0.02 * code for code in range(16)],
        ]
        default = [row[8] for row in responses]
        calibration = choose_calibration(responses)
        self.assertLess(calibration["spread_db"], spread_db(default))
        self.assertEqual(calibration["codes_ch0_to_ch3"], [11, 9, 7, 5])
        self.assertLessEqual(
            calibration["maximum_absolute_gain_shift_from_default_db"], 2.0
        )

    def test_sub_significance_spread_does_not_throw_away_nominal_gain(self) -> None:
        curve = [0.80 + 0.02 * code for code in range(16)]
        responses = [
            [value * factor for value in curve]
            for factor in (1.0, 1.00001, 0.99999, 1.00002)
        ]
        calibration = choose_calibration(responses)
        self.assertEqual(calibration["codes_ch0_to_ch3"], [8, 8, 8, 8])
        self.assertAlmostEqual(calibration["mean_gain_shift_from_default_db"], 0.0)

    def test_gain_limit_is_enforced_per_channel_not_only_on_mean(self) -> None:
        responses = [
            [0.5 + 0.0625 * code for code in range(16)],
            [1.5 - 0.0625 * code for code in range(16)],
            [1.0 for _ in range(16)],
            [1.0 for _ in range(16)],
        ]
        calibration = choose_calibration(responses, maximum_gain_shift_db=0.5)
        self.assertLessEqual(
            calibration["maximum_absolute_gain_shift_from_default_db"], 0.5
        )
        self.assertTrue(
            all(
                abs(value) <= 0.5
                for value in calibration["gain_shift_from_default_db_by_channel"]
            )
        )

    def test_injected_mismatch_stress_is_explicit_and_correctable(self) -> None:
        curve = [0.80 + 0.02 * code for code in range(16)]
        result = injected_mismatch_stress([curve.copy() for _ in range(4)])
        self.assertIn("not foundry mismatch Monte Carlo", result["method"])
        self.assertAlmostEqual(result["untrimmed_code8_spread_db"], 1.2)
        self.assertLess(result["calibration"]["spread_db"], 0.1)

    def test_spread_rejects_a_zero_response(self) -> None:
        self.assertEqual(spread_db([0.0, 1.0]), float("inf"))

    def test_report_path_exactly_names_the_smoke_case(self) -> None:
        path = case_report_path(2, 7, "base", 5.0, 2.0, 3.0)
        self.assertEqual(
            path.name,
            "report.json",
        )
        self.assertEqual(
            path.parent.name,
            "selected_0_incident_0_mask_4_startup_op_window_2us_3us_step_5ns_"
            "trim_8_8_7_8",
        )

    def test_monotonicity_allows_tiny_numeric_ripple_but_rejects_inversion(self) -> None:
        small_ripple = [1.0 + 0.01 * code for code in range(16)]
        small_ripple[2] = small_ripple[1] * 0.9995
        self.assertEqual(monotonicity(small_ripple)["status"], "pass")
        inversion = [1.0 + 0.01 * code for code in range(16)]
        inversion[2] = inversion[1] * 0.98
        result = monotonicity(inversion)
        self.assertEqual(result["status"], "fail")
        self.assertIn(1, result["inverted_steps_after_codes"])

    def test_useful_resolution_rejects_aliased_adjacent_codes(self) -> None:
        resolved = [1.0 * (10.0 ** (0.05 * code / 20.0)) for code in range(16)]
        self.assertEqual(useful_resolution(resolved)["status"], "pass")
        aliased = resolved.copy()
        aliased[7] = aliased[6]
        result = useful_resolution(aliased)
        self.assertEqual(result["status"], "fail")
        self.assertIn(6, result["under_resolved_steps_after_codes"])

    def test_case_runner_uses_a_post_commit_integer_cycle_window(self) -> None:
        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        import unittest.mock

        with unittest.mock.patch(
            "run_control_postlayout_trim_calibration.subprocess.run",
            return_value=Completed(),
        ) as mocked:
            run_case(0, 7, "base", "ngspice", 900, 5.0, 2.0, 3.0)
        command = mocked.call_args.args[0]
        self.assertEqual(command[command.index("--analysis-start-us") + 1], "2.0")
        self.assertEqual(command[command.index("--analysis-stop-us") + 1], "3.0")


if __name__ == "__main__":
    unittest.main()
    injected_mismatch_stress,
