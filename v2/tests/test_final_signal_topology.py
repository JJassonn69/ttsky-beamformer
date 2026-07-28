import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_final_signal_topology import audit


class FinalSignalTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = ROOT / "build/v2/control_routing"
        cls.spice = (base / "quadrature_extraction/control_quadrature_hier.spice").read_text()
        cls.flat = (base / "quadrature_extraction/control_quadrature_flat.spice").read_text()
        cls.geometry = json.loads((base / "openroad_route_geometry.json").read_text())
        cls.log = (base / "direct/quadrature_magic_extraction.log").read_text()

    def test_final_named_terminal_topology_passes(self) -> None:
        report = audit(self.spice, self.flat, self.geometry, self.log)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["checked_instance_count"], 156)
        self.assertEqual(report["critical_flat_net_count"], 30)

    def test_mixer_gate_swap_is_rejected(self) -> None:
        mutated = self.spice.replace(
            "XCH0_SW1_A ch0_lop ", "XCH0_SW1_A ch0_lon ", 1
        )
        self.assertNotEqual(mutated, self.spice)
        report = audit(mutated, self.flat, self.geometry, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("XCH0_SW1_A.G" in error for error in report["errors"]))

    def test_resistor_end_bypass_is_rejected(self) -> None:
        mutated = self.spice.replace(
            "XLOAD_P VGND ch0_out_p VDPWR",
            "XLOAD_P VGND ch0_out_p ch0_out_p",
            1,
        )
        self.assertNotEqual(mutated, self.spice)
        report = audit(mutated, self.flat, self.geometry, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("XLOAD_P.R1" in error for error in report["errors"]))

    def test_missing_flat_critical_net_is_rejected(self) -> None:
        mutated = self.flat.replace("ch3_tail", "BROKEN_CH3_TAIL")
        report = audit(self.spice, mutated, self.geometry, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertIn("ch3_tail", report["missing_flat_nets"])


if __name__ == "__main__":
    unittest.main()
