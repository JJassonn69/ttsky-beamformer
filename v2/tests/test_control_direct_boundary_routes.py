import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlDirectBoundaryRoutesTest(unittest.TestCase):
    """Guard the nine boundary nets in their current unified-router owner."""

    @classmethod
    def setUpClass(cls) -> None:
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.expected = {
            item["net"] for item in allocation["nets"]
            if item["class"] == "direct_boundary"
        }
        cls.geometry = json.loads(
            (ROOT / "build/v2/control_routing/openroad_route_geometry.json").read_text()
        )
        route_audit = json.loads(
            (ROOT / "build/v2/control_routing/openroad/route_audit.json").read_text()
        )
        cls.routed = {
            item["net"]: item for item in route_audit["nets"]
            if item["net"] in cls.expected
        }
        topology = json.loads(
            (ROOT / "build/v2/control_routing/quadrature_extraction/"
             "all_routes_topology_audit.json").read_text()
        )
        cls.extracted = {
            item["logical_net"]: item for item in topology["routes"]
            if item["logical_net"] in cls.expected
        }

    def test_all_nine_nets_are_owned_by_the_unified_router(self) -> None:
        self.assertEqual(len(self.expected), 9)
        self.assertEqual(set(self.routed), self.expected)
        self.assertEqual(set(self.extracted), self.expected)
        self.assertTrue(self.expected <= set(self.geometry["label_net_map"].values()))

    def test_routes_are_compact_acyclic_connected_trees(self) -> None:
        for route in self.routed.values():
            self.assertEqual(route["electrical_group_count"], 1)
            self.assertEqual(route["cycle_rank"], 0)
            self.assertEqual(route["unattached_leaf_count"], 0)
            self.assertLessEqual(route["detour_ratio"], 1.60)
            self.assertNotIn("met4", route["layers"])

    def test_final_extraction_reaches_the_exact_mapped_pin_multiset(self) -> None:
        for route in self.extracted.values():
            self.assertEqual(route["status"], "pass")
            self.assertEqual(route["actual_endpoints"], route["expected_endpoints"])


if __name__ == "__main__":
    unittest.main()
