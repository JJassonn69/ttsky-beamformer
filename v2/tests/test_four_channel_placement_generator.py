import json
import sys
import tempfile
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from generate_four_channel_placement import generate


class FourChannelPlacementGeneratorTests(unittest.TestCase):
    def test_all_repeated_components_are_emitted_once(self) -> None:
        def read(name: str):
            return json.loads((V2_ROOT / "layout" / name).read_text())

        with tempfile.TemporaryDirectory() as directory:
            def_path = Path(directory) / "placement.def"
            tcl_path = Path(directory) / "placement.tcl"
            standard, analog = generate(
                read("floorplan.json"),
                read("pcell_dimensions.json"),
                read("channel_template.json"),
                def_path,
                tcl_path,
            )
            def_text = def_path.read_text()
            tcl_text = tcl_path.read_text()
        self.assertEqual(standard, 64)
        self.assertEqual(analog, 114)
        self.assertIn("COMPONENTS 64", def_text)
        self.assertEqual(def_text.count("+ FIXED"), 64)
        for index in range(4):
            self.assertIn(f"CH{index}_PMUX_A", def_text)
            self.assertIn(f"identify CH{index}_RINPUT", tcl_text)
        self.assertIn("identify LOAD_P", tcl_text)
        self.assertIn("identify LOAD_N", tcl_text)
        self.assertIn("FOUR_CHANNEL_PLACEMENT_DRC_COUNT", tcl_text)
        self.assertIn("FOUR_CHANNEL_PLACEMENT_GDS_FEEDBACK_COUNT", tcl_text)


if __name__ == "__main__":
    unittest.main()
