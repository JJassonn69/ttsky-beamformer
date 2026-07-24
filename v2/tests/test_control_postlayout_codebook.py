import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_codebook import (
    case_report_is_reusable,
    case_report_path,
    corrected_response_matrices,
    evaluate_matrix,
    operating_ranges,
    summary_report_path,
    validate_case_identity,
    validate_settled_measurements,
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

    def test_pvt_case_reports_cannot_overwrite_nominal_reports(self) -> None:
        path = case_report_path(
            "base", 1, 2, process_corner="ss", supply_voltage_v=1.62,
            temperature_c=85.0,
        )
        self.assertEqual(
            path.name,
            "report.json",
        )
        self.assertIn("_corner_ss_vdd_1p62_temp_85c", path.parent.name)

    def test_calibrated_case_reports_cannot_overwrite_default_trim(self) -> None:
        path = case_report_path("base", 0, 0, trim_codes=(7, 8, 9, 8))
        self.assertIn("_trim_7_8_9_8", path.parent.name)
        self.assertNotEqual(path, case_report_path("base", 0, 0))

    def test_coarse_pvt_timestep_is_explicit_in_case_path(self) -> None:
        path = case_report_path("base", 0, 0, transient_step_ns=5.0)
        self.assertIn("_step_5ns", path.parent.name)

    def test_nondefault_timestep_cannot_overwrite_default_summary(self) -> None:
        default = summary_report_path("base")
        coarse = summary_report_path("base", transient_step_ns=5.0)
        self.assertEqual(default.name, "summary_startup_op.json")
        self.assertEqual(coarse.name, "summary_startup_op_step_5ns.json")
        self.assertNotEqual(default, coarse)

    def test_passive_corner_is_explicit_in_case_path(self) -> None:
        path = case_report_path("base", 0, 0, passive_corner="hh")
        self.assertIn("_passives_hh", path.parent.name)

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

    def test_nominal_constructive_spread_above_three_db_fails(self) -> None:
        matrix = [
            [1.5 if row == column == 0 else 1.0 if row == column else 0.01
             for column in range(4)]
            for row in range(4)
        ]
        metrics, errors = evaluate_matrix(matrix)
        self.assertGreater(metrics["constructive_spread_db"], 3.0)
        self.assertTrue(any("constructive spread" in error for error in errors))

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

    def test_case_identity_binds_startup_and_artifact_hashes(self) -> None:
        report = {
            "view": "base",
            "startup": "op",
            "selected_beam": 2,
            "incident_beam": 3,
            "input_peak_v": 0.005,
            "process_corner": "tt",
            "supply_voltage_v": 1.8,
            "temperature_c": 27.0,
            "transient_step_ns": 2.0,
            "gds_sha256": "a" * 64,
            "netlist_sha256": "b" * 64,
            "spiceinit_sha256": "c" * 64,
        }
        self.assertEqual(
            validate_case_identity(
                report,
                view="base",
                startup="op",
                selected_beam=2,
                incident_beam=3,
                input_peak_v=0.005,
            ),
            [],
        )
        report["startup"] = "uic"
        report["gds_sha256"] = "short"
        errors = validate_case_identity(
            report,
            view="base",
            startup="op",
            selected_beam=2,
            incident_beam=3,
            input_peak_v=0.005,
        )
        self.assertTrue(any("startup" in error for error in errors))
        self.assertTrue(any("gds_sha256" in error for error in errors))

    def test_reused_reports_must_have_settled_bias_and_current(self) -> None:
        report = {
            "measurements": {
                "vcm_avg": 1.199,
                "common_mode_avg": 0.985,
                "supply_avg": -695e-6,
            }
        }
        self.assertEqual(validate_settled_measurements(report), [])
        report["measurements"]["vcm_avg"] = 0.5
        self.assertTrue(
            any("VCM" in error for error in validate_settled_measurements(report))
        )

    def test_resume_reuses_only_exact_current_passing_reports(self) -> None:
        report = {
            "status": "pass",
            "view": "rc",
            "startup": "op",
            "selected_beam": 2,
            "incident_beam": 3,
            "input_peak_v": 0.005,
            "process_corner": "tt",
            "supply_voltage_v": 1.8,
            "temperature_c": 27.0,
            "transient_step_ns": 2.0,
            "gds_sha256": "a" * 64,
            "netlist_sha256": "b" * 64,
            "spiceinit_sha256": "c" * 64,
            "measurements": {
                "vcm_avg": 1.199,
                "common_mode_avg": 0.972,
                "supply_avg": -695e-6,
            },
        }
        arguments = {
            "view": "rc",
            "startup": "op",
            "selected_beam": 2,
            "incident_beam": 3,
            "input_peak_v": 0.005,
            "gds_sha256": "a" * 64,
            "netlist_sha256": "b" * 64,
        }
        self.assertTrue(case_report_is_reusable(report, **arguments))
        report["netlist_sha256"] = "d" * 64
        self.assertFalse(case_report_is_reusable(report, **arguments))

    def test_operating_ranges_include_power(self) -> None:
        reports = {
            (0, 0, 0.005): {
                "measurements": {
                    "vcm_avg": 1.198,
                    "common_mode_avg": 0.984,
                    "supply_avg": -690e-6,
                }
            },
            (1, 1, 0.005): {
                "measurements": {
                    "vcm_avg": 1.200,
                    "common_mode_avg": 0.986,
                    "supply_avg": -700e-6,
                }
            },
        }
        ranges = operating_ranges(reports)
        self.assertEqual(ranges["vcm_v"], [1.198, 1.2])
        self.assertEqual(ranges["supply_current_a"], [690e-6, 700e-6])
        self.assertAlmostEqual(ranges["estimated_power_w"][1], 1.26e-3)


if __name__ == "__main__":
    unittest.main()
