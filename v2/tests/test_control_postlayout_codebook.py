import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_codebook import (
    case_report_path,
    corrected_response_matrices,
    evaluate_matrix,
)


class ControlPostlayoutCodebookTests(unittest.TestCase):
    def test_case_reports_are_isolated_by_selected_and_incident_beam(self) -> None:
        path = case_report_path("base", 2, 3)
        self.assertEqual(
            path.relative_to(ROOT),
            Path(
                "build/v2/postlayout_smoke/base/codebook/"
                "selected_2_incident_3_startup_op/report.json"
            ),
        )
        baseline = case_report_path("base", 2, 3, input_peak_v=0.0)
        self.assertEqual(
            baseline.relative_to(ROOT),
            Path(
                "build/v2/postlayout_smoke/base/codebook/"
                "selected_2_incident_3_vin_0nv_startup_op/report.json"
            ),
        )
        uic = case_report_path("base", 2, 3, startup="uic")
        self.assertEqual(
            uic.relative_to(ROOT),
            Path(
                "build/v2/postlayout_smoke/base/codebook/"
                "selected_2_incident_3/report.json"
            ),
        )

    def test_case_report_rejects_unknown_startup(self) -> None:
        with self.assertRaises(ValueError):
            case_report_path("base", 2, 3, startup="unknown")

    def test_idealized_ten_to_one_diagonal_has_twenty_db_rejection(self) -> None:
        matrix = [
            [1.0 if row == column else 0.1 for column in range(4)]
            for row in range(4)
        ]
        metrics, errors = evaluate_matrix(matrix)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(metrics["minimum_rejection_db"], 20.0)
        self.assertAlmostEqual(metrics["constructive_spread_db"], 0.0)

    def test_matrix_below_functional_gate_fails(self) -> None:
        matrix = [
            [1.0 if row == column else 0.6 for column in range(4)]
            for row in range(4)
        ]
        _, errors = evaluate_matrix(matrix, minimum_rejection_db=6.0)
        self.assertEqual(len(errors), 4)

    def test_matrix_shape_is_strict(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_matrix([[1.0]])

    def test_complex_background_is_subtracted_before_magnitude(self) -> None:
        reports = {}
        for selected in range(4):
            baseline_incident = (selected + 1) % 4
            reports[(selected, baseline_incident, 0.0)] = {
                "analysis": {
                    "output_tone_i_v": 2.0,
                    "output_tone_q_v": -1.0,
                    "output_tone_rms_v": 5.0,
                }
            }
            for incident in range(4):
                wanted = 1.0 if selected == incident else 0.1
                reports[(selected, incident, 0.005)] = {
                    "analysis": {
                        "output_tone_i_v": 2.0 + wanted,
                        "output_tone_q_v": -1.0,
                        "output_tone_rms_v": 9.0,
                    }
                }
        corrected, raw, background = corrected_response_matrices(reports)
        self.assertAlmostEqual(corrected[0][0], 2 ** 0.5)
        self.assertAlmostEqual(corrected[0][1], 0.1 * 2 ** 0.5)
        self.assertEqual(raw[0][0], 9.0)
        self.assertEqual(background[0], [2.0, -1.0])


if __name__ == "__main__":
    unittest.main()
