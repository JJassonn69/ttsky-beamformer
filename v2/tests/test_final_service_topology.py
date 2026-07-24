import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_service_topology import audit


class FinalServiceTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = ROOT / "build/v2/control_routing"
        cls.spice = (base / "quadrature_extraction/control_quadrature_hier.spice").read_text()
        cls.log = (base / "direct/quadrature_magic_extraction.log").read_text()
        cls.mapping = json.loads((ROOT / "build/v2/control_mapping/physical_netlist.json").read_text())
        allocation = json.loads((base / "control_route_allocation.json").read_text())
        cls.routes = [
            item for item in allocation["nets"]
            if item["class"] in ("direct_boundary", "service_tree")
        ]
        geometry = json.loads((base / "openroad_route_geometry.json").read_text())
        cls.physical = {
            logical: label for label, logical in geometry["label_net_map"].items()
        }

    def run_audit(self, spice: str):
        return audit(
            spice, self.mapping, self.routes, self.log,
            "v2_control_quadrature_routed", "CONTROL_QUADRATURE", self.physical,
        )

    def test_all_final_service_and_direct_routes_pass(self) -> None:
        report = self.run_audit(self.spice)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["verified_named_route_count"], 15)

    def test_broken_reset_endpoint_is_rejected(self) -> None:
        reset_label = self.physical["rst_n"]
        mutated = self.spice.replace(reset_label, "BROKEN_RESET_ENDPOINT", 1)
        self.assertNotEqual(mutated, self.spice)
        report = self.run_audit(mutated)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("rst_n" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
