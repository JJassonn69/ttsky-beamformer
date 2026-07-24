import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_power_topology import audit


class ControlServiceTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spice = (
            ROOT / "build/v2/control_routing/quadrature_extraction/"
            "control_quadrature_hier.spice"
        ).read_text(errors="replace")
        cls.mapping = json.loads(
            (ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()
        )
        cls.log = (
            ROOT / "build/v2/control_routing/direct/"
            "quadrature_magic_extraction.log"
        ).read_text(errors="replace")
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.expected = {
            item["net"] for item in allocation["nets"]
            if item["class"] == "service_tree"
        }
        topology = json.loads(
            (ROOT / "build/v2/control_routing/quadrature_extraction/"
             "all_routes_topology_audit.json").read_text()
        )
        cls.routes = [
            item for item in topology["routes"]
            if item["logical_net"] in cls.expected
        ]

    def run_power_audit(self, spice: str | None = None):
        return audit(
            spice if spice is not None else self.spice,
            self.mapping,
            self.log,
            "v2_control_quadrature_routed",
            "CONTROL_QUADRATURE",
        )

    def test_final_exact_extraction_preserves_all_service_routes(self) -> None:
        self.assertEqual(len(self.routes), 6)
        self.assertEqual(
            {item["logical_net"] for item in self.routes}, self.expected
        )
        self.assertTrue(all(item["status"] == "pass" for item in self.routes))

    def test_final_exact_extraction_preserves_power_and_analog_topology(self) -> None:
        report = self.run_power_audit()
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(
            report["verified_standard_cell_power_and_body_pins"]
            + report["verified_fixed_helper_power_and_body_pins"],
            968,
        )
        self.assertEqual(
            {item["instance"] for item in report["analog_vdpwr_checks"]},
            {"RBIAS", "RVCM_TOP", "LOAD_N", "LOAD_P"},
        )

    def test_final_gate_rejects_a_grounded_output_load(self) -> None:
        lines = self.spice.splitlines()
        active = ""
        changed = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.lower().startswith(".subckt "):
                active = stripped.split()[1]
            elif stripped.lower() == ".ends":
                active = ""
            elif (
                active == "v2_control_quadrature_routed"
                and raw.startswith("XLOAD_N") and "VDPWR" in raw
            ):
                lines[index] = raw.replace("VDPWR", "VGND", 1)
                changed = True
                break
        self.assertTrue(changed, "fixture has no powered LOAD_N R1 terminal")
        report = self.run_power_audit("\n".join(lines))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("LOAD_N.R1" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
