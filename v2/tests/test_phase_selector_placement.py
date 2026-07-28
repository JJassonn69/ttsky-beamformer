import json
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from study_phase_selector_placement import run_study


class PhaseSelectorPlacementTests(unittest.TestCase):
    def test_first_stage_outputs_face_inward(self) -> None:
        report = run_study(
            json.loads((V2_ROOT / "layout/channel_template.json").read_text()),
            json.loads((V2_ROOT / "layout/pcell_dimensions.json").read_text()),
            json.loads((V2_ROOT / "layout/port_catalog.json").read_text()),
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["selected"], "inward_outputs")
        self.assertGreater(report["reduction_vs_baseline_um_per_channel"], 3.0)
        components = {
            item["name"]: item
            for item in json.loads(
                (V2_ROOT / "layout/channel_template.json").read_text()
            )["components"]
        }
        self.assertAlmostEqual(
            (components["PMUX_P"]["x"] + components["PMUX_N"]["x"]) / 2,
            0.92,
        )


if __name__ == "__main__":
    unittest.main()
