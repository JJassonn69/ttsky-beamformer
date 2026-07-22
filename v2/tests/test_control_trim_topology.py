import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_trim_topology import audit


class ControlTrimTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def test_all_sixteen_routes_reach_all_three_endpoint_roles(self) -> None:
        report = audit(
            self.spice, self.mapping, self.geometry, self.log,
            "v2_control_quadrature_routed", "CONTROL_QUADRATURE",
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["verified_trim_role_count"], 48)
        self.assertEqual(report["magic_exttospice_completion_count"], 2)

    def test_disconnected_endpoint_role_is_rejected(self) -> None:
        physical = next(
            label for label, net in self.geometry["label_net_map"].items()
            if net == "active_trim_codes[0]"
        )
        mutated = self.spice.replace(physical, "BROKEN_TRIM_TEST", 1)
        self.assertNotEqual(mutated, self.spice)
        report = audit(
            mutated, self.mapping, self.geometry, self.log,
            "v2_control_quadrature_routed", "CONTROL_QUADRATURE",
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("active_trim_codes[0]" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
