import json
import unittest
from pathlib import Path

from v2.tools.check_control_final_rc import audit


ROOT = Path(__file__).resolve().parents[2]


class ControlFinalRcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / "build/v2/control_routing/final_rc"
        cls.geometry = json.loads(
            (ROOT / "build/v2/control_routing/openroad_route_geometry.json").read_text()
        )
        cls.report = audit(
            cls.work / "control_final_base.spice",
            cls.work / "control_final_rc.spice",
            cls.work / "v2_control_final_rc_flat.res.ext",
            cls.geometry,
            (cls.work / "magic_rc.log").read_text(errors="replace"),
        )

    def test_zero_pruning_rc_covers_the_complete_final_design(self):
        self.assertEqual(self.report["status"], "pass")
        self.assertTrue(all(self.report["checks"].values()))
        self.assertEqual(self.report["required_control_route_count"], 206)
        self.assertEqual(self.report["required_analog_route_count"], 47)
        self.assertEqual(self.report["required_routed_net_count"], 254)
        self.assertEqual(self.report["covered_routed_net_count"], 254)
        self.assertEqual(self.report["uncovered_routed_nets"], [])
        self.assertEqual(
            self.report["output_pad_rc_endpoints"]["sum_p"]["matched_rnode"],
            "ch0_out_p.n0",
        )
        self.assertEqual(
            self.report["output_pad_rc_endpoints"]["sum_n"]["matched_rnode"],
            "ch0_out_n.n0",
        )

    def test_rc_view_is_distributed_and_device_complete(self):
        base = self.report["base"]
        rc = self.report["distributed_rc"]
        self.assertEqual(base["resistors"], 0)
        self.assertGreater(rc["resistors"], 90000)
        self.assertGreater(rc["capacitors"], base["capacitors"])
        self.assertEqual(rc["devices"], base["devices"])
        self.assertEqual(rc["devices"], 4244)
        self.assertGreater(rc["internal_resistor_nodes"], 60000)
        self.assertGreaterEqual(
            self.report["annotation"]["spice_to_annotation_ratio"], 0.90
        )


if __name__ == "__main__":
    unittest.main()
