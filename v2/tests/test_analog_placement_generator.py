import json
import sys
import tempfile
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from generate_analog_placement_tcl import generate


class AnalogPlacementGeneratorTests(unittest.TestCase):
    def test_my_uses_magic_horizontal_reflection(self) -> None:
        dimensions = json.loads(
            (V2_ROOT / "layout" / "pcell_dimensions.json").read_text()
        )
        template = json.loads(
            (V2_ROOT / "layout" / "channel_template.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "place.tcl"
            count = generate(dimensions, template, output)
            text = output.read_text()
        self.assertEqual(count, 28)
        self.assertIn("identify GM_REF_A", text)
        self.assertIn("parent ll h 0 0", text)
        self.assertNotIn("parent ll v 0 0", text)
        self.assertNotIn("PMUX_A", text)
        self.assertIn("file delete -force", text)
        self.assertIn("ANALOG_PLACEMENT_GDS_FEEDBACK_COUNT", text)
        self.assertIn("refusing analog placement artifact", text)


if __name__ == "__main__":
    unittest.main()
