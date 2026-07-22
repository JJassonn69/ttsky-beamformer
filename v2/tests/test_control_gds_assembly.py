import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_control_placement_gds import (
    ANGLE,
    SREF,
    STRANS,
    TOP,
    assemble,
    record_type,
    records,
    split_library,
    structure_name,
)
from generate_control_placement_tcl import generate as generate_magic_placement
from check_magic_rc_log import FATAL_PATTERNS


class ControlGDSAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ROOT / "build/v2/support_routes/magic/v2_four_channel_support_routed.gds"
        cls.output = ROOT / "build/v2/control_placement/direct/v2_four_channel_control_placed.gds"
        cls.placement = json.loads(
            (ROOT / "build/v2/control_placement/control_placement.json").read_text()
        )

    def test_assembly_is_byte_deterministic(self) -> None:
        data, report = assemble(
            self.source,
            "v2_four_channel_support_routed",
            self.placement,
            ROOT / "third_party/sky130_fd_sc_hd_cells",
        )
        self.assertEqual(data, self.output.read_bytes())
        self.assertEqual(report["sref_count_added"], self.placement["counts"]["total_instances"])
        self.assertEqual(report["imported_structure_count"], 9)

    def test_top_contains_exact_reference_transforms(self) -> None:
        _, source_structures, _ = split_library(records(self.source.read_bytes()))
        _, output_structures, _ = split_library(records(self.output.read_bytes()))
        source_top = next(
            item for item in source_structures
            if structure_name(item) == "v2_four_channel_support_routed"
        )
        output_top = next(item for item in output_structures if structure_name(item) == TOP)
        counts = lambda structure, kind: sum(record_type(item) == kind for item in structure)
        instances = (
            self.placement["placements"]
            + self.placement["well_taps"]
            + self.placement.get("fillers", [])
        )
        expected_strans = sum(item["orientation"] != "R0" for item in instances)
        expected_angles = sum(item["orientation"] in ("MY", "R180") for item in instances)
        self.assertEqual(
            counts(output_top, SREF) - counts(source_top, SREF),
            self.placement["counts"]["total_instances"],
        )
        self.assertEqual(counts(output_top, STRANS) - counts(source_top, STRANS), expected_strans)
        self.assertEqual(counts(output_top, ANGLE) - counts(source_top, ANGLE), expected_angles)

    def test_every_angle_is_preceded_by_strans_in_its_reference(self) -> None:
        _, output_structures, _ = split_library(records(self.output.read_bytes()))
        output_top = next(item for item in output_structures if structure_name(item) == TOP)
        reference_records = []
        inside = False
        for record in output_top:
            if record_type(record) == SREF:
                inside = True
                reference_records = [record]
            elif inside:
                reference_records.append(record)
                if record_type(record) == 0x11:  # ENDEL
                    if any(record_type(item) == ANGLE for item in reference_records):
                        self.assertTrue(
                            any(record_type(item) == STRANS for item in reference_records)
                        )
                    inside = False

    def test_every_placed_cell_structure_is_present(self) -> None:
        _, structures, _ = split_library(records(self.output.read_bytes()))
        names = {structure_name(item) for item in structures}
        referenced = {
            item["cell"]
            for item in (
                self.placement["placements"]
                + self.placement["well_taps"]
                + self.placement.get("fillers", [])
            )
        }
        self.assertTrue(referenced <= names)

    def test_magic_stage_is_drc_only_and_does_not_rebuild_vendor_gds(self) -> None:
        integration = json.loads(
            (ROOT / "v2/layout/integration_plan.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "place.tcl"
            count = generate_magic_placement(self.placement, integration, output)
            text = output.read_text()
        self.assertEqual(count, self.placement["counts"]["total_instances"])
        self.assertIn("gds readonly yes", text)
        self.assertIn("CONTROL_PLACEMENT_GDS_POLICY=direct_hierarchy_assembly", text)
        self.assertNotIn("gds write", text)

    def test_exact_placement_gds_import_log_has_no_silent_errors(self) -> None:
        text = (
            ROOT / "build/v2/control_placement/direct/magic_import_drc.log"
        ).read_text(errors="replace")
        self.assertIn("CONTROL_DIRECT_GDS_DRC_COUNT=0", text)
        self.assertIn("CONTROL_DIRECT_GDS_FEEDBACK_COUNT=0", text)
        for name, pattern in FATAL_PATTERNS.items():
            self.assertIsNone(pattern.search(text), name)


if __name__ == "__main__":
    unittest.main()
