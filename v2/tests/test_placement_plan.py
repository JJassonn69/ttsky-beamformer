import json
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from check_placement_plan import validate_placement_plan


class V2PlacementPlanTests(unittest.TestCase):
    def test_repeated_measured_channel_template(self) -> None:
        report = validate_placement_plan(
            json.loads((V2_ROOT / "layout" / "floorplan.json").read_text()),
            json.loads((V2_ROOT / "layout" / "pcell_dimensions.json").read_text()),
            json.loads((V2_ROOT / "layout" / "channel_template.json").read_text()),
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["bbox_overlap_count"], 0)
        self.assertEqual(report["fixed_trim_fingers"], 32)
        self.assertEqual(report["binary_trim_fingers"], [1, 2, 4, 8])
        self.assertEqual(report["gm_branch_p_centroid"], report["gm_branch_n_centroid"])


if __name__ == "__main__":
    unittest.main()
