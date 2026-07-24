import json
import unittest
from pathlib import Path

from v2.tools.check_control_openroad_flat_gds import audit


ROOT = Path(__file__).resolve().parents[2]


class ControlOpenroadFlatGdsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit(
            ROOT / "build/v2/control_power/direct/v2_four_channel_control_powered.gds",
            "v2_four_channel_control_powered",
            ROOT / "build/v2/control_routing/openroad_internal/direct/v2_control_internal_routed.gds",
            "v2_control_internal_routed",
            json.loads(
                (ROOT / "v2/layout/control_openroad_route_plan.json").read_text()
            ),
        )

    def test_internal_routes_add_no_flattened_rule_markers(self):
        self.assertEqual(self.report["status"], "pass")
        self.assertEqual(self.report["errors"], [])
        self.assertEqual(
            self.report["candidate_marker_count_by_rule"],
            self.report["inherited_marker_count_by_rule"],
        )
        self.assertEqual(
            self.report["candidate_marker_count_by_rule"]["met4 minimum width"],
            1,
        )
        self.assertEqual(
            sum(self.report["candidate_marker_count_by_rule"].values()), 1
        )

    def test_only_thirteen_external_routes_add_metal4_and_via3(self):
        source = self.report["source_geometry"]
        candidate = self.report["candidate_geometry"]
        self.assertGreater(candidate["met4_rectangles"], source["met4_rectangles"])
        self.assertEqual(candidate["via3_cuts"], source["via3_cuts"] + 13)
        self.assertGreater(candidate["met3_rectangles"], source["met3_rectangles"])


if __name__ == "__main__":
    unittest.main()
