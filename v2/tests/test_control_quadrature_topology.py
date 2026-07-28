import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_control_quadrature_topology import audit


class ControlQuadratureTopologyTests(unittest.TestCase):
    def test_four_roots_roles_and_power_survive(self) -> None:
        allocation = json.loads((ROOT / "build/v2/control_routing/control_route_allocation.json").read_text())
        openroad = json.loads((ROOT / "build/v2/control_routing/openroad_route_geometry.json").read_text())
        physical_labels = {
            logical: physical for physical, logical in openroad["label_net_map"].items()
        }
        report = audit(
            (ROOT / "build/v2/control_routing/quadrature_extraction/control_quadrature_hier.spice").read_text(errors="replace"),
            json.loads((ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()),
            [item for item in allocation["nets"] if item["class"] == "quadrature_handoff"],
            (ROOT / "build/v2/control_routing/direct/quadrature_magic_extraction.log").read_text(errors="replace"),
            physical_labels,
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["verified_quadrature_net_count"], 4)
        self.assertEqual(report["mapped_standard_cell_count"], 194)
        self.assertEqual(report["fixed_helper_standard_cell_count"], 48)
        self.assertEqual(report["verified_standard_cell_power_and_body_pins"], 968)
        self.assertEqual(report["unexpected_signal_to_power_short_count"], 0)


if __name__ == "__main__":
    unittest.main()
