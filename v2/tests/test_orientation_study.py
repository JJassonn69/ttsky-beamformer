import json
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from run_orientation_study import run_study


class V2OrientationStudyTests(unittest.TestCase):
    def test_source_facing_pair_is_selected(self) -> None:
        report = run_study(
            json.loads((V2_ROOT / "layout" / "pcell_dimensions.json").read_text()),
            json.loads((V2_ROOT / "layout" / "channel_template.json").read_text()),
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["selected"], "source_facing_pairs")
        self.assertGreater(report["source_route_reduction_vs_all_r0_um_per_channel"], 0.0)


if __name__ == "__main__":
    unittest.main()
