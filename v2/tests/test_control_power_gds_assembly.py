import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_control_placement_gds import SNAME, SREF, ascii_payload, record_type, records, split_library, structure_name
from assemble_control_power_gds import STRING, TEXT, assemble
from check_magic_rc_log import FATAL_PATTERNS


class ControlPowerGDSAssemblyTests(unittest.TestCase):
    source = ROOT / "build/v2/control_placement/direct/v2_four_channel_control_placed.gds"
    # The exact overlay emitted by the pinned remote Magic run lives under
    # overlay/magic; the sibling file is an older local preview and is not a
    # release checkpoint.
    overlay = ROOT / "build/v2/control_power/overlay/magic/v2_control_power_overlay.gds"
    output = ROOT / "build/v2/control_power/direct/v2_four_channel_control_powered.gds"

    def test_assembly_is_byte_deterministic(self) -> None:
        data, report = assemble(
            self.source, "v2_four_channel_control_placed",
            self.overlay, "v2_control_power_overlay",
            "v2_four_channel_control_powered",
        )
        self.assertEqual(data, self.output.read_bytes())
        self.assertEqual(report["overlay_reference_count_added"], 1)
        self.assertEqual(report["overlay_structure_count"], 1)
        self.assertEqual(report["top_level_power_labels_promoted"], ["VDPWR", "VGND"])

    def test_only_one_overlay_reference_is_added_to_the_top(self) -> None:
        _, source_structures, _ = split_library(records(self.source.read_bytes()))
        _, output_structures, _ = split_library(records(self.output.read_bytes()))
        source_top = next(
            item for item in source_structures
            if structure_name(item) == "v2_four_channel_control_placed"
        )
        output_top = next(
            item for item in output_structures
            if structure_name(item) == "v2_four_channel_control_powered"
        )
        source_srefs = sum(record_type(item) == SREF for item in source_top)
        output_srefs = sum(record_type(item) == SREF for item in output_top)
        self.assertEqual(output_srefs - source_srefs, 1)
        self.assertIn(
            "v2_control_power_overlay",
            [ascii_payload(item) for item in output_top if record_type(item) == SNAME],
        )

    def test_power_labels_are_promoted_into_the_assembled_top(self) -> None:
        _, output_structures, _ = split_library(records(self.output.read_bytes()))
        output_top = next(
            item for item in output_structures
            if structure_name(item) == "v2_four_channel_control_powered"
        )
        self.assertGreaterEqual(sum(record_type(item) == TEXT for item in output_top), 2)
        strings = [
            ascii_payload(item) for item in output_top if record_type(item) == STRING
        ]
        self.assertIn("VDPWR", strings)
        self.assertIn("VGND", strings)

    def test_all_source_and_overlay_structures_are_preserved(self) -> None:
        _, source_structures, _ = split_library(records(self.source.read_bytes()))
        _, overlay_structures, _ = split_library(records(self.overlay.read_bytes()))
        _, output_structures, _ = split_library(records(self.output.read_bytes()))
        source_names = {structure_name(item) for item in source_structures}
        source_names.remove("v2_four_channel_control_placed")
        overlay_names = {structure_name(item) for item in overlay_structures}
        output_names = {structure_name(item) for item in output_structures}
        self.assertTrue(source_names <= output_names)
        self.assertTrue(overlay_names <= output_names)

    def test_assembly_report_matches_frozen_artifact(self) -> None:
        report = json.loads(
            (ROOT / "build/v2/control_power/direct/gds_assembly_audit.json").read_text()
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["output_top"], "v2_four_channel_control_powered")

    def test_exact_gds_magic_import_log_is_unambiguously_clean(self) -> None:
        text = (
            ROOT / "build/v2/control_power/direct/magic_import_drc.log"
        ).read_text(errors="replace")
        self.assertIn("CONTROL_POWER_DIRECT_GDS_DRC_COUNT=0", text)
        self.assertIn("CONTROL_POWER_DIRECT_GDS_FEEDBACK_COUNT=0", text)
        for name, pattern in FATAL_PATTERNS.items():
            self.assertIsNone(pattern.search(text), name)


if __name__ == "__main__":
    unittest.main()
