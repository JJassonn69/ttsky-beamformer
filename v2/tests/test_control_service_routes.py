import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlServiceRoutesTest(unittest.TestCase):
    """Guard the six high-fanout controls in the unified OpenROAD result."""

    @classmethod
    def setUpClass(cls) -> None:
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.expected = {
            item["net"] for item in allocation["nets"]
            if item["class"] == "service_tree"
        }
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

    def test_all_six_service_nets_have_one_current_owner(self) -> None:
        self.assertEqual(
            self.expected,
            {"apply_config", "cfg_clk", "cfg_latch", "clk", "rst_n",
             "serial_phase_to_trim"},
        )
        self.assertEqual(set(self.routed), self.expected)
        self.assertEqual(set(self.extracted), self.expected)

    def test_high_fanout_routes_are_connected_acyclic_and_bounded(self) -> None:
        for route in self.routed.values():
            self.assertEqual(route["electrical_group_count"], 1)
            self.assertEqual(route["cycle_rank"], 0)
            self.assertEqual(route["unattached_leaf_count"], 0)
            self.assertLessEqual(route["detour_ratio"], 1.82)
        self.assertEqual(
            {net for net, route in self.routed.items() if "met4" in route["layers"]},
            {"cfg_clk", "cfg_latch", "clk", "rst_n"},
        )

    def test_final_extraction_reaches_every_mapped_service_pin(self) -> None:
        for route in self.extracted.values():
            self.assertEqual(route["status"], "pass")
            self.assertEqual(route["actual_endpoints"], route["expected_endpoints"])


if __name__ == "__main__":
    unittest.main()
