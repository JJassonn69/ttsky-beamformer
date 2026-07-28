import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_openroad_topology import audit


class ControlFinalTopologyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spice = (
            ROOT / "build/v2/control_routing/quadrature_extraction/"
            "control_quadrature_hier.spice"
        ).read_text(errors="replace")
        cls.mapping = json.loads(
            (ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()
        )
        cls.geometry = json.loads(
            (ROOT / "build/v2/control_routing/openroad_route_geometry.json").read_text()
        )
        cls.log = (
            ROOT / "build/v2/control_routing/direct/"
            "quadrature_magic_extraction.log"
        ).read_text(errors="replace")
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.handoff_extensions = {
            item["net"] for item in allocation["nets"]
            if item["class"] in {
                "trim_handoff", "phase_handoff", "quadrature_handoff"
            }
        }

    def run_audit(self, spice: str | None = None):
        return audit(
            spice if spice is not None else self.spice,
            self.mapping,
            self.geometry,
            self.log,
            "v2_control_quadrature_routed",
            "CONTROL_QUADRATURE",
            self.handoff_extensions,
        )

    def test_all_final_routes_match_exact_cell_pin_multisets(self):
        report = self.run_audit()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["route_count"], 206)
        self.assertEqual(report["verified_route_count"], 206)
        self.assertEqual(report["expected_endpoint_count"], 718)
        self.assertEqual(report["verified_endpoint_count"], 790)
        self.assertEqual(report["extracted_unique_route_label_count"], 206)

    def test_missing_terminal_is_detected_in_the_final_gds_view(self):
        damaged = self.spice.replace(" R000 ", " BROKEN ", 1)
        self.assertNotEqual(damaged, self.spice)
        report = self.run_audit(damaged)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("R000" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
