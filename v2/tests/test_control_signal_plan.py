import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from plan_control_signal_routes import plan_routes


class ControlSignalPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "v2/layout/control_signal_plan.json").read_text())
        cls.mapping = json.loads(
            (ROOT / "build/v2/control_mapping/physical_netlist.json").read_text()
        )
        cls.placement = json.loads(
            (ROOT / "build/v2/control_placement/control_placement.json").read_text()
        )
        cls.floorplan = json.loads((ROOT / "v2/layout/floorplan.json").read_text())
        cls.integration = json.loads((ROOT / "v2/layout/integration_plan.json").read_text())
        cls.frozen = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )

    def run_plan(self, plan=None, integration=None):
        return plan_routes(
            plan or self.plan,
            self.mapping,
            self.placement,
            self.floorplan,
            integration or self.integration,
            ROOT,
        )

    def test_all_207_nets_have_a_feasible_named_topology(self) -> None:
        report = self.run_plan()
        self.assertEqual(report, self.frozen)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["mapped_signal_net_count"], 207)
        self.assertEqual(report["planned_signal_net_count"], 207)
        self.assertEqual(report["mapped_pin_endpoint_count"], 719)
        self.assertEqual(report["physical_anchor_count"], 45)
        self.assertNotIn("unplanned_cross_region", report["class_counts"])
        blanking = next(item for item in report["nets"] if item["net"] == "mixers_blank")
        self.assertEqual(blanking["class"], "observation_only")
        self.assertEqual(blanking["anchor_count"], 0)
        self.assertEqual(blanking["topology"], "no_physical_route")
        self.assertTrue(all(
            item["margin_track_count"] >= 6
            for item in report["track_capacity"].values()
        ))

    def test_undersized_track_window_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["routing_windows"]["phase_configuration_bank"]["available_track_count"] = 5
        report = self.run_plan(plan=plan)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("needs" in item and "M4 tracks" in item for item in report["errors"]))

    def test_missing_one_pin_handoff_is_rejected(self) -> None:
        integration = copy.deepcopy(self.integration)
        integration["phase_control_handoffs"]["routes"] = [
            item for item in integration["phase_control_handoffs"]["routes"]
            if not (item["signal"] == "phase_select0" and item["channel"] == 0)
        ]
        report = self.run_plan(integration=integration)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("one-pin mapped nets" in item for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
