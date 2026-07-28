import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_control_quadrature_routes import validate
from generate_control_quadrature_routes import generate, magic_tcl
from check_gds_flat_rules import flatten_rectangles, parse_gds


class ControlQuadratureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "v2/layout/control_quadrature_route_plan.json").read_text())
        cls.allocation = json.loads((ROOT / "build/v2/control_routing/control_route_allocation.json").read_text())
        cls.geometry = json.loads((ROOT / "build/v2/control_routing/quadrature_geometry.json").read_text())
        cls.power = json.loads((ROOT / "build/v2/control_power/control_power_geometry.json").read_text())
        cls.trim = json.loads((ROOT / "build/v2/control_routing/trim_geometry.json").read_text())
        cls.phase = json.loads((ROOT / "build/v2/control_routing/phase_geometry.json").read_text())
        structures, db = parse_gds(ROOT / "build/v2/control_routing/direct/v2_control_phase_routed.gds")
        cls.source = flatten_rectangles(structures, "v2_control_phase_routed", db)

    def test_geometry_is_deterministic_connected_and_clear(self) -> None:
        self.assertEqual(generate(self.plan, self.allocation, ROOT), self.geometry)
        report = validate(self.geometry, self.plan, self.power, self.trim, self.phase, self.source)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["route_count"], 4)
        self.assertEqual(report["mapped_pin_count"], 10)
        self.assertEqual(report["cut_count_by_layer"],
                         {"viali": 0, "via1": 0, "via2": 2, "via3": 0})
        self.assertEqual(report["planned_source_root_and_boundary_join_count"], 14)
        self.assertEqual(report["unexpected_source_interaction_count"], 0)
        self.assertEqual({item["layer"] for item in self.geometry["shapes"]},
                         {"metal2", "via2", "metal3"})
        self.assertLessEqual(report["analog_drop_spread_um"], 0.6)
        self.assertEqual(sum(
            item["direction_reversals"] for item in self.geometry["routes"]
        ), 1)

    def test_existing_router_vias_are_reused_where_locally_efficient(self) -> None:
        manual = set(self.plan["manual_boundary_via_nets"])
        self.assertEqual(manual, {"phase_wave[0]", "phase_wave[3]"})
        for route in self.geometry["routes"]:
            self.assertEqual(route["via_counts"]["via2"], int(route["net"] in manual))

    def test_oversized_manual_via_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        cut = next(item for item in geometry["shapes"] if item["layer"] == "via2")
        x0, y0, _x1, _y1 = cut["bbox_um"]
        cut["bbox_um"] = [x0, y0, x0 + .40, y0 + .40]
        report = validate(
            geometry, self.plan, self.power, self.trim, self.phase, self.source
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("must be one 0.20x0.20" in item for item in report["errors"]))

    def test_root_column_crossing_an_existing_m2_net_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        root = next(item for item in geometry["shapes"]
                    if item["net"] == "phase_wave[0]" and item["kind"] == "root_column")
        root["bbox_um"][0], root["bbox_um"][2] = 119.74, 120.06
        report = validate(geometry, self.plan, self.power, self.trim, self.phase, self.source)
        self.assertGreater(report["unexpected_source_interaction_count"], 0)

    def test_magic_writer_has_hard_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "quadrature.tcl"
            magic_tcl(self.geometry, target)
            text = target.read_text()
        self.assertIn("CONTROL_QUADRATURE_OVERLAY_DRC_COUNT", text)
        self.assertIn("CONTROL_QUADRATURE_OVERLAY_GDS_FEEDBACK_COUNT", text)


if __name__ == "__main__":
    unittest.main()
