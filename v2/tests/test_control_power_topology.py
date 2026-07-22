import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_power_topology import TOP, audit


class ControlPowerTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spice = (
            ROOT / "build/v2/control_power/extraction/control_power_hier.spice"
        ).read_text(errors="replace")
        cls.mapping = json.loads(
            (ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()
        )
        cls.log = (
            ROOT / "build/v2/control_power/direct/magic_extraction.log"
        ).read_text(errors="replace")

    def test_exact_extraction_has_every_supply_and_body_connection(self) -> None:
        report = audit(self.spice, self.mapping, self.log)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["mapped_standard_cell_count"], 194)
        self.assertEqual(report["verified_standard_cell_power_and_body_pins"], 776)
        self.assertEqual(report["unexpected_signal_to_power_short_count"], 0)
        self.assertEqual(report["fixed_helper_standard_cell_count"], 48)
        self.assertEqual(report["verified_fixed_helper_power_and_body_pins"], 192)
        self.assertEqual(report["fixed_helper_unexpected_signal_to_power_short_count"], 0)
        self.assertEqual(
            {item["instance"] for item in report["analog_vdpwr_checks"]},
            {"RBIAS", "RVCM_TOP", "LOAD_N", "LOAD_P"},
        )
        self.assertTrue(all(
            item["B"] == "VGND" and item["R1"] == "VDPWR"
            for item in report["analog_vdpwr_checks"]
        ))

    def test_one_disconnected_extracted_supply_pin_is_rejected(self) -> None:
        lines = self.spice.splitlines()
        active = ""
        changed = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.lower().startswith(".subckt "):
                active = stripped.split()[1]
            elif stripped.lower() == ".ends":
                active = ""
            elif active == TOP and raw.startswith("Xsky130_fd_sc_hd__") and "VDPWR" in raw:
                lines[index] = raw.replace("VDPWR", "FLOAT_TEST", 1)
                changed = True
                break
        self.assertTrue(changed, "fixture has no mapped-cell VDPWR connection")
        report = audit("\n".join(lines), self.mapping, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("expected VDPWR" in item for item in report["errors"]))

    def test_fatal_magic_import_marker_is_rejected(self) -> None:
        report = audit(
            self.spice,
            self.mapping,
            self.log + "\nUnexpected record type in input: Expected XY but got ANGLE\n",
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["magic_log_fatal_matches"])

    def test_one_disconnected_helper_supply_pin_is_rejected(self) -> None:
        lines = self.spice.splitlines()
        active = ""
        changed = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.lower().startswith(".subckt "):
                active = stripped.split()[1]
            elif stripped.lower() == ".ends":
                active = ""
            elif active == TOP and raw.startswith("XCH0_TINV0") and "VDPWR" in raw:
                lines[index] = raw.replace("VDPWR", "FLOAT_HELPER_TEST", 1)
                changed = True
                break
        self.assertTrue(changed, "fixture has no helper-cell VDPWR connection")
        report = audit("\n".join(lines), self.mapping, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("CH0_TINV0" in item for item in report["errors"]))

    def test_output_load_r1_short_to_ground_is_rejected(self) -> None:
        lines = self.spice.splitlines()
        active = ""
        changed = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.lower().startswith(".subckt "):
                active = stripped.split()[1]
            elif stripped.lower() == ".ends":
                active = ""
            elif active == TOP and raw.startswith("XLOAD_P") and "VDPWR" in raw:
                lines[index] = raw.replace("VDPWR", "VGND", 1)
                changed = True
                break
        self.assertTrue(changed, "fixture has no powered LOAD_P R1 terminal")
        report = audit("\n".join(lines), self.mapping, self.log)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("LOAD_P.R1" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
