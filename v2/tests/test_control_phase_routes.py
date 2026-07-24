import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_phase_routes import validate
from generate_control_phase_routes import generate, magic_tcl
from check_gds_flat_rules import flatten_rectangles, parse_gds


class ControlPhaseRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "v2/layout/control_phase_route_plan.json").read_text())
        cls.allocation = json.loads((ROOT / "build/v2/control_routing/control_route_allocation.json").read_text())
        cls.geometry = json.loads((ROOT / "build/v2/control_routing/phase_geometry.json").read_text())
        cls.power = json.loads((ROOT / "build/v2/control_power/control_power_geometry.json").read_text())
        cls.trim = json.loads((ROOT / "build/v2/control_routing/trim_geometry.json").read_text())
        structures, database_um = parse_gds(
            ROOT / "build/v2/control_routing/direct/v2_control_trim_routed.gds"
        )
        cls.source_rectangles = flatten_rectangles(
            structures, "v2_control_trim_routed", database_um
        )

    def test_geometry_is_deterministic_connected_and_clear(self) -> None:
        self.assertEqual(generate(self.plan, self.allocation, ROOT), self.geometry)
        report = validate(self.geometry, self.plan, self.power, self.trim,
                          self.source_rectangles)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["route_count"], 12)
        self.assertEqual(report["cut_count_by_layer"],
                         {"viali": 0, "via1": 0, "via2": 12, "via3": 4})
        self.assertEqual(report["cross_stage_spacing_error_count"], {})
        self.assertGreaterEqual(report["planned_source_endpoint_join_count"], 12)
        self.assertEqual(report["unexpected_source_interaction_count"], 0)
        self.assertTrue(all(route["selector_interface_um"][1] == 151.0
                            for route in self.geometry["routes"]))
        self.assertEqual(
            sum(item["kind"] == "interface_via3_m3"
                for item in self.geometry["shapes"]),
            0,
        )

    def test_route_stopping_at_transition_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        route = geometry["routes"][0]
        route["selector_interface_um"][1] = route["handoff_um"][1]
        report = validate(geometry, self.plan, self.power, self.trim)
        self.assertEqual(report["status"], "fail")

    def test_existing_phase_root_crossing_is_rejected_before_extraction(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        shape = next(
            item for item in geometry["shapes"]
            if item["net"] == "phase_enable[2]" and item["kind"] == "analog_root_column"
        )
        shape["bbox_um"][0] = 120.92
        shape["bbox_um"][2] = 121.24
        report = validate(geometry, self.plan, self.power, self.trim,
                          self.source_rectangles)
        self.assertGreater(report["unexpected_source_interaction_count"], 0)
        self.assertEqual(report["status"], "fail")

    def test_missing_via_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        geometry["shapes"].remove(next(s for s in geometry["shapes"] if s["layer"] == "via2"))
        report = validate(geometry, self.plan, self.power, self.trim)
        self.assertEqual(report["status"], "fail")

    def test_oversized_direct_gds_cut_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        cut = next(item for item in geometry["shapes"] if item["layer"] == "via2")
        x0, y0, _x1, _y1 = cut["bbox_um"]
        cut["bbox_um"] = [x0, y0, x0 + .40, y0 + .40]
        report = validate(geometry, self.plan, self.power, self.trim)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("must be one 0.20x0.20" in item for item in report["errors"]))

    def test_narrow_interface_jog_notch_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        jog = next(item for item in geometry["shapes"] if item["kind"] == "interface_jog")
        centre = (jog["bbox_um"][1] + jog["bbox_um"][3]) / 2
        jog["bbox_um"][1], jog["bbox_um"][3] = centre - .13, centre + .13
        report = validate(geometry, self.plan, self.power, self.trim)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("leaves an M2 notch" in item for item in report["errors"]))

    def test_magic_writer_has_hard_drc_and_feedback_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase.tcl"
            magic_tcl(self.geometry, path)
            text = path.read_text()
        self.assertIn("CONTROL_PHASE_OVERLAY_DRC_COUNT", text)
        self.assertIn("CONTROL_PHASE_OVERLAY_GDS_FEEDBACK_COUNT", text)


if __name__ == "__main__":
    unittest.main()
