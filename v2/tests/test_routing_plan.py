from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from check_routing_plan import validate


class RoutingPlanTests(unittest.TestCase):
    def test_lane_spacing_symmetry_and_trim_order(self) -> None:
        report = validate(
            json.loads((ROOT / "v2/layout/routing_plan.json").read_text()),
            json.loads((ROOT / "v2/layout/channel_template.json").read_text()),
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["same_layer_conflicts"], [])
        self.assertEqual(report["track_count"], 13)


if __name__ == "__main__":
    unittest.main()
