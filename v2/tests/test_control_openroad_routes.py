import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_openroad_routes import parse_route, validate


class ControlOpenroadRouteTest(unittest.TestCase):
    def test_openroad_patch_rectangles_are_valid_zero_length_conductors(self):
        block = "NEW met1 ( 41665 8070 ) RECT ( 0 -70 320 70 ) ;"
        segments, vias, layers, extension = parse_route(block)
        self.assertEqual(segments, [])
        self.assertEqual(vias, [])
        self.assertEqual(layers, {"met1"})
        self.assertAlmostEqual(extension, 0.18)

    def test_every_internal_net_is_a_connected_drc_clean_tree(self):
        output = ROOT / "build/v2/control_routing/openroad"
        result = validate(
            output / "openroad_jobs.json",
            ROOT / "build/v2/control_routing/control_route_allocation.json",
            ROOT / "build/v2/control_placement/control_placement.json",
            ROOT / "build/v2/control_mapping/physical_netlist.json",
            output,
        )
        self.assertEqual(result["status"], "pass", result["errors"])
        self.assertEqual(result["internal_net_count"], 206)
        self.assertEqual(result["expected_internal_net_count"], 206)
        self.assertNotEqual(result["maximum_route_layer"], "met5")
        self.assertGreater(result["total_wire_length_um"], 0.0)
        self.assertGreater(result["total_via_count"], 0)
        self.assertTrue(all(item["electrical_group_count"] == 1 for item in result["nets"]))
        self.assertTrue(all(item["cycle_rank"] == 0 for item in result["nets"]))


if __name__ == "__main__":
    unittest.main()
