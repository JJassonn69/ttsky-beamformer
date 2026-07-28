import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlDirectBoundaryTopologyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.expected = {
            item["net"] for item in allocation["nets"]
            if item["class"] == "direct_boundary"
        }
        topology = json.loads(
            (ROOT / "build/v2/control_routing/quadrature_extraction/"
             "all_routes_topology_audit.json").read_text()
        )
        cls.routes = [
            item for item in topology["routes"]
            if item["logical_net"] in cls.expected
        ]
        cls.power = json.loads(
            (ROOT / "build/v2/control_routing/quadrature_extraction/"
             "power_topology_audit.json").read_text()
        )

    def test_extracted_direct_boundary_roles_are_exact_in_final_gds(self) -> None:
        self.assertEqual(len(self.routes), 9)
        self.assertTrue(all(item["status"] == "pass" for item in self.routes))
        self.assertTrue(all(
            item["actual_endpoints"] == item["expected_endpoints"]
            for item in self.routes
        ))

    def test_final_cells_supplies_and_analog_loads_remain_intact(self) -> None:
        self.assertEqual(self.power["status"], "pass")
        self.assertEqual(self.power["mapped_standard_cell_count"], 194)
        self.assertEqual(self.power["fixed_helper_standard_cell_count"], 48)
        self.assertEqual(
            self.power["verified_standard_cell_power_and_body_pins"]
            + self.power["verified_fixed_helper_power_and_body_pins"],
            968,
        )
        self.assertEqual(self.power["unexpected_signal_to_power_short_count"], 0)
        self.assertEqual(
            {item["instance"] for item in self.power["analog_vdpwr_checks"]},
            {"RBIAS", "RVCM_TOP", "LOAD_N", "LOAD_P"},
        )


if __name__ == "__main__":
    unittest.main()
