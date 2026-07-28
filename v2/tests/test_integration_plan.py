import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = ROOT / "v2"
sys.path.insert(0, str(V2_ROOT / "tools"))

from check_integration_plan import validate


class V2IntegrationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((V2_ROOT / "layout/integration_plan.json").read_text())
        cls.floorplan = json.loads((V2_ROOT / "layout/floorplan.json").read_text())
        cls.dimensions = json.loads(
            (V2_ROOT / "layout/pcell_dimensions.json").read_text()
        )
        cls.stats = json.loads(
            (ROOT / "build/v2/control_synthesis/generic_stats.json").read_text()
        )

    def check(self, plan):
        return validate(plan, self.floorplan, self.dimensions, self.stats, ROOT)

    def test_production_integration_contract(self) -> None:
        report = self.check(self.plan)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["phase_handoff_count"], 12)
        self.assertEqual(len(report["trim_tracks"]), 16)
        self.assertLessEqual(
            max(report["conservative_region_utilization"].values()), 0.55
        )

    def test_m4_trim_transition_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["trim_control_bus"]["transition_layers"] = [
            "metal2", "via2", "metal3", "via3", "metal4"
        ]
        self.assertEqual(self.check(plan)["status"], "fail")

    def test_moved_phase_handoff_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["phase_control_handoffs"]["routes"][0]["x"] += 0.5
        self.assertEqual(self.check(plan)["status"], "fail")

    def test_stale_base_gds_hash_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["base_checkpoint"]["sha256"] = "0" * 64
        self.assertEqual(self.check(plan)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
