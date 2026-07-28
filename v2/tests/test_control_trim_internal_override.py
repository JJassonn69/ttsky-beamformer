import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_trim_internal_override import validate
from generate_control_openroad_overlay import apply_route_geometry_override, generate


class ControlTrimInternalOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.override = json.loads(
            (ROOT / "v2/layout/control_trim_internal_route_override.json").read_text()
        )
        cls.plan = json.loads(
            (ROOT / "v2/layout/control_openroad_route_plan.json").read_text()
        )

    def test_override_is_bounded_and_self_consistent(self) -> None:
        report = validate(self.override)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["route_count"], 16)
        self.assertEqual(report["shape_count"], 490)
        self.assertEqual(report["via_count"], 69)

    def test_generated_geometry_uses_only_the_frozen_trim_override(self) -> None:
        geometry = generate(self.plan, ROOT)
        overridden = {
            item["net"] for item in geometry["routes"]
            if item.get("reviewed_manual_override")
        }
        self.assertEqual(
            overridden, {f"active_trim_codes[{index}]" for index in range(16)}
        )
        self.assertEqual(geometry["counts"]["shapes"], 6223)
        self.assertEqual(geometry["counts"]["vias"], 1466)

    def test_changed_top_pin_is_rejected(self) -> None:
        geometry = generate(self.plan, ROOT)
        override = copy.deepcopy(self.override)
        victim = override["routes"][0]
        top_pin = next(
            item for item in victim["shapes"]
            if item["kind"] == "openroad_top_pin"
        )
        top_pin["bbox_um"][0] += 0.005
        with self.assertRaisesRegex(ValueError, "changes a frozen top pin"):
            apply_route_geometry_override(
                geometry["shapes"], geometry["routes"], geometry["labels"], override
            )

    def test_unrelated_net_override_is_rejected(self) -> None:
        geometry = generate(self.plan, ROOT)
        override = copy.deepcopy(self.override)
        override["routes"][0]["net"] = "clk"
        with self.assertRaisesRegex(ValueError, "not limited to active trim codes"):
            apply_route_geometry_override(
                geometry["shapes"], geometry["routes"], geometry["labels"], override
            )


if __name__ == "__main__":
    unittest.main()
