import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_control_placement_gds import records, split_library, structure_name
from assemble_vcm_varactor_eco_gds import (
    EXPECTED_OUTPUT_SHA256,
    SOURCE_SHA256,
    SOURCE_TOP,
    VARACTOR_CELL,
    assemble,
    sref_targets,
)
from generate_vcm_varactor_eco import generate


class VcmVaractorEcoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(
            (ROOT / "v2/layout/vcm_varactor_eco.json").read_text()
        )
        cls.dimensions = json.loads(
            (ROOT / "v2/layout/pcell_dimensions.json").read_text()
        )
        cls.catalog = json.loads(
            (ROOT / "v2/layout/port_catalog.json").read_text()
        )

    def test_overlay_generator_adds_only_four_direct_varactor_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "eco.tcl"
            metrics = generate(
                self.plan, self.dimensions, self.catalog, output
            )
            text = output.read_text()
        self.assertEqual(metrics["varactor_count"], 4)
        self.assertEqual(metrics["direction_reversals"], 0)
        self.assertEqual(metrics["orphan_vias"], 0)
        for terminal, access in zip(
            metrics["gate_points_um"], metrics["gate_access_points_um"]
        ):
            self.assertEqual(access[0], terminal[0])
            self.assertAlmostEqual(access[1] - terminal[1], 0.32)
        self.assertEqual(text.count("\ngetcell "), 4)
        self.assertEqual(text.count("\nidentify CVCM_VAR"), 4)
        self.assertIn("build/v2/pcell_bbox_remote", text)
        self.assertNotIn("SOURCE_GDS", text)
        self.assertNotIn("support_routed", text)

    def test_tracked_user_source_and_final_candidate_are_hash_bound(self) -> None:
        source = ROOT / self.plan["source_checkpoint"]["gds"]
        candidate = ROOT / self.plan["output_checkpoint"]["gds"]
        self.assertEqual(
            hashlib.sha256(source.read_bytes()).hexdigest(), SOURCE_SHA256
        )
        self.assertEqual(
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
            EXPECTED_OUTPUT_SHA256,
        )
        self.assertEqual(
            self.plan["source_checkpoint"]["sha256"], SOURCE_SHA256
        )
        self.assertEqual(
            self.plan["output_checkpoint"]["sha256"], EXPECTED_OUTPUT_SHA256
        )

    def test_final_gds_contains_exactly_four_direct_varactor_references(self) -> None:
        candidate = (
            ROOT
            / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
        )
        _header, structures, _endlib = split_library(records(candidate.read_bytes()))
        names = [structure_name(item) for item in structures]
        self.assertEqual(names.count(VARACTOR_CELL), 1)
        top = next(item for item in structures if structure_name(item) == SOURCE_TOP)
        self.assertEqual(sref_targets(top).count(VARACTOR_CELL), 4)

    def test_assembler_rejects_any_source_other_than_user_edited_gds(self) -> None:
        with self.assertRaisesRegex(
            ValueError, rf"!= user-routed source {SOURCE_SHA256}"
        ):
            assemble(b"not the frozen user GDS", b"")


if __name__ == "__main__":
    unittest.main()
