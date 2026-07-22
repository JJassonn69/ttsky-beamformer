import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = ROOT / "v2"

import sys
sys.path.insert(0, str(V2_ROOT / "tools"))

from generate_support_placement import generate


class SupportPlacementGeneratorTests(unittest.TestCase):
    def test_clean_measured_support_placement(self) -> None:
        plan = json.loads((V2_ROOT / "layout/integration_plan.json").read_text())
        dimensions = json.loads(
            (V2_ROOT / "layout/pcell_dimensions.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "place.tcl"
            count = generate(plan, dimensions, output)
            text = output.read_text()
        self.assertEqual(count, 6)
        self.assertEqual(text.count("\nidentify "), 6)
        self.assertIn("identify CVCM", text)
        self.assertNotIn("identify CVCM_VAR", text)
        self.assertIn("identify BIAS_DIODE_A", text)
        self.assertIn("identify BIAS_DIODE_B", text)
        self.assertIn("SUPPORT_PLACEMENT_DRC_COUNT", text)
        self.assertIn("gds read $SOURCE_GDS", text)
        self.assertNotIn("load v2_four_channel_support_placed -silent", text)


if __name__ == "__main__":
    unittest.main()
