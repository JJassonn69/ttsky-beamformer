import hashlib
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
sys.path.insert(0, str(ROOT / "tools"))

from assemble_control_placement_gds import (  # noqa: E402
    STRNAME,
    record_type,
    records,
    split_library,
    structure_name,
)
from generate_submission_gds import (  # noqa: E402
    LANDING_PLAN,
    MET4_DRAW,
    MET4_PIN,
    OUTPUT,
    RELOCATION_PLAN,
    SOURCE,
    SOURCE_SHA256,
    SOURCE_TOP,
    SUBMISSION_TOP,
    TEMPLATE_DEF,
    package,
)
from check_gds_flat_rules import parse_gds  # noqa: E402
from template_pins import submission_pins  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SubmissionArtifactsTest(unittest.TestCase):
    def test_submission_gds_adds_exact_official_pin_purposes(self) -> None:
        source = SOURCE.read_bytes()
        self.assertEqual(sha256(source), SOURCE_SHA256)
        expected, report = package(SOURCE)
        self.assertEqual(OUTPUT.read_bytes(), expected)
        repeated, repeated_report = package(SOURCE)
        self.assertEqual(repeated, expected)
        self.assertEqual(repeated_report, report)
        self.assertEqual(report["changed_existing_gds_records"], 1)
        self.assertEqual(report["added_pin_polygon_count"], 53)
        self.assertEqual(report["added_signal_pin_drawing_polygon_count"], 51)
        self.assertEqual(report["added_gds_records"], 520)

        _, output_structures, _ = split_library(records(expected))
        self.assertNotIn(SOURCE_TOP, {
            structure_name(item) for item in output_structures
        })
        self.assertEqual(report["electrical_repaired_sha256"],
                         "54281f763eec7b24cc995865b0a812fcb6ab1e1932d8062e55e77a31c74f6eb2")
        self.assertEqual(report["landing_plan_sha256"],
                         hashlib.sha256(LANDING_PLAN.read_bytes()).hexdigest())
        self.assertEqual(report["relocation_plan_sha256"],
                         hashlib.sha256(RELOCATION_PLAN.read_bytes()).hexdigest())
        repair = report["official_precheck_repair"]
        self.assertEqual(repair["redundant_top_mcon_removed"], 692)
        self.assertEqual(repair["redundant_top_m1_landings_removed"], 470)
        self.assertEqual(repair["dense_via1_m1_landings_narrowed"], 132)
        self.assertEqual(repair["dense_via1_landings_relocated"], 132)
        self.assertEqual(repair["mixer_via2_cuts_relocated"], 8)

        structures, database_um = parse_gds(OUTPUT)
        pin_polygons = [
            polygon
            for layer, polygon in structures[SUBMISSION_TOP].polygons
            if layer == MET4_PIN
        ]
        actual = {
            tuple(
                round(value * database_um * 1000)
                for value in (
                    min(point[0] for point in polygon),
                    min(point[1] for point in polygon),
                    max(point[0] for point in polygon),
                    max(point[1] for point in polygon),
                )
            )
            for polygon in pin_polygons
        }
        _, _, pins = submission_pins(TEMPLATE_DEF)
        expected_rectangles = {pin.rect_nm for pin in pins}
        self.assertEqual(len(pin_polygons), 53)
        self.assertEqual(actual, expected_rectangles)

        drawing_rectangles = {
            tuple(
                round(value * database_um * 1000)
                for value in (
                    min(point[0] for point in polygon),
                    min(point[1] for point in polygon),
                    max(point[0] for point in polygon),
                    max(point[1] for point in polygon),
                )
            )
            for layer, polygon in structures[SUBMISSION_TOP].polygons
            if layer == MET4_DRAW
        }
        expected_signal_rectangles = {
            pin.rect_nm for pin in pins if pin.use == "SIGNAL"
        }
        self.assertEqual(len(expected_signal_rectangles), 51)
        self.assertTrue(expected_signal_rectangles <= drawing_rectangles)

    def test_lef_matches_the_2x2_template_and_power_contract(self) -> None:
        lef = (ROOT / f"lef/{SUBMISSION_TOP}.lef").read_text()
        self.assertIn(f"MACRO {SUBMISSION_TOP}", lef)
        self.assertIn("SIZE 334.880 BY 225.760 ;", lef)
        self.assertEqual(len(re.findall(r"^\s*PIN \S+", lef, re.MULTILINE)), 53)
        for pin in ("ua[0]", "ua[1]", "ua[2]", "ua[3]", "ua[4]", "ua[5]"):
            self.assertIn(f"PIN {pin}", lef)
        self.assertIn("PIN VDPWR", lef)
        self.assertIn("PIN VGND", lef)
        self.assertNotIn("PIN VAPWR", lef)

    def test_clean_ci_fetches_pinned_def_before_lef_regeneration(self) -> None:
        workflow = (ROOT / ".github/workflows/gds.yaml").read_text()
        fetch = "python3 v2/tools/fetch_tt_2x2_template.py"
        generate = "python3 tools/generate_submission_lef.py"
        self.assertIn(fetch, workflow)
        self.assertIn(generate, workflow)
        self.assertLess(workflow.index(fetch), workflow.index(generate))

        fetch_script = (ROOT / "v2/tools/fetch_tt_2x2_template.py").read_text()
        lock = (ROOT / "submission/template.lock").read_text()
        def_sha = re.search(r'^def_sha256=(\w+)$', lock, re.MULTILINE)
        self.assertIsNotNone(def_sha)
        self.assertIn(f'SHA256 = "{def_sha.group(1)}"', fetch_script)

    def test_info_yaml_is_v2_submission_metadata(self) -> None:
        info = (ROOT / "info.yaml").read_text()
        for fragment in (
            'clock_hz:     16000000',
            'tiles:        "2x2"',
            'analog_pins:  6',
            'uses_vapwr:   false',
            'ua[4]: "BEAM_OUT_P"',
            'ua[5]: "BEAM_OUT_N"',
        ):
            self.assertIn(fragment, info)
        self.assertNotIn("Two-Channel", info)
        self.assertNotIn("CH2_PHASE_180", info)

    def test_verilog_stub_is_the_v2_black_box_contract(self) -> None:
        source = (ROOT / "src/project.v").read_text()
        self.assertNotIn("CH2_PHASE_180", source)
        self.assertIn("ui_in, uio_in, ua[7:6]", source)
        self.assertIn("assign uo_out  = 8'b0;", source)
        self.assertIn("assign uio_oe  = 8'b0;", source)


if __name__ == "__main__":
    unittest.main()
