import hashlib
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_control_placement_gds import (  # noqa: E402
    STRNAME,
    record_type,
    records,
    split_library,
    structure_name,
)
from generate_submission_gds import (  # noqa: E402
    OUTPUT,
    SOURCE,
    SOURCE_SHA256,
    SOURCE_TOP,
    SUBMISSION_TOP,
    package,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SubmissionArtifactsTest(unittest.TestCase):
    def test_submission_gds_is_only_a_top_name_change(self) -> None:
        source = SOURCE.read_bytes()
        self.assertEqual(sha256(source), SOURCE_SHA256)
        expected, report = package(source)
        self.assertEqual(OUTPUT.read_bytes(), expected)
        self.assertEqual(report["changed_gds_records"], 1)
        self.assertEqual(report["geometry_records_changed"], 0)

        _, source_structures, _ = split_library(records(source))
        _, output_structures, _ = split_library(records(expected))
        self.assertEqual(len(source_structures), len(output_structures))
        for before, after in zip(source_structures, output_structures):
            before_name = structure_name(before)
            after_name = structure_name(after)
            if before_name != SOURCE_TOP:
                self.assertEqual(before, after)
                self.assertEqual(before_name, after_name)
                continue
            self.assertEqual(after_name, SUBMISSION_TOP)
            stripped_before = [item for item in before if record_type(item) != STRNAME]
            stripped_after = [item for item in after if record_type(item) != STRNAME]
            self.assertEqual(stripped_before, stripped_after)

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
