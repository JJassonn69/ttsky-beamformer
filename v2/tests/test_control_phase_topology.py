import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_control_phase_topology import audit


class ControlPhaseTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        allocation = json.loads((ROOT / "build/v2/control_routing/control_route_allocation.json").read_text())
        cls.mapping = {
            "mapping": json.loads((ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()),
            "phase_routes": [item for item in allocation["nets"] if item["class"] == "phase_handoff"],
        }
        cls.spice = (ROOT / "build/v2/control_routing/phase_extraction/control_phase_hier.spice").read_text(errors="replace")
        cls.log = (ROOT / "build/v2/control_routing/direct/phase_magic_extraction.log").read_text(errors="replace")

    def test_all_phase_roles_and_power_pins_survive(self) -> None:
        report = audit(self.spice, self.mapping, self.log)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["verified_phase_net_count"], 12)
        self.assertEqual(report["mapped_standard_cell_count"], 194)
        self.assertEqual(report["fixed_helper_standard_cell_count"], 48)
        self.assertEqual(report["verified_standard_cell_power_and_body_pins"], 968)
        self.assertEqual(report["unexpected_signal_to_power_short_count"], 0)


if __name__ == "__main__":
    unittest.main()
