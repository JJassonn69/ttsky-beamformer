import json
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from check_floorplan import validate_floorplan
from check_cell_fit import validate_cell_fit


class V2FloorplanTests(unittest.TestCase):
    def setUp(self) -> None:
        manifest = V2_ROOT / "layout" / "floorplan.json"
        self.data = json.loads(manifest.read_text(encoding="utf-8"))
        dimensions = V2_ROOT / "layout" / "pcell_dimensions.json"
        self.dimensions = json.loads(dimensions.read_text(encoding="utf-8"))

    def test_floorplan_contract(self) -> None:
        report = validate_floorplan(self.data)
        self.assertEqual(report["status"], "pass", report["errors"])

    def test_no_critical_net_class_allows_direction_reversal(self) -> None:
        for name, net_class in self.data["net_classes"].items():
            self.assertEqual(
                net_class["max_direction_reversals"],
                0,
                f"{name} permits an avoidable route reversal",
            )

    def test_trim_is_channel_local_and_has_no_cross_macro_analog_route(self) -> None:
        trim = self.data["gain_trim"]
        self.assertIn("inside the owning channel", trim["placement_rule"])
        self.assertIn("no analog trim net", trim["routing_rule"])
        self.assertFalse(
            self.data["net_classes"]["trim_controls"][
                "analog_trim_routes_crossing_channel_boundaries"
            ]
        )

    def test_r2r_trade_study_is_not_silently_in_the_release_floorplan(self) -> None:
        self.assertEqual(
            self.data["r2r_trade_study"]["status"],
            "excluded from V2A production placement",
        )

    def test_output_trunks_have_named_keepouts(self) -> None:
        keepout_names = {keepout["name"] for keepout in self.data["keepouts"]}
        self.assertIn("combined_p_vertical_trunk", keepout_names)
        self.assertIn("combined_n_vertical_trunk", keepout_names)

    def test_output_routes_start_on_measured_resistor_ports(self) -> None:
        catalog = json.loads(
            (V2_ROOT / "layout" / "port_catalog.json").read_text(encoding="utf-8")
        )
        r2 = catalog["analog_pcells"]["output_load_resistor_guarded"]["ports"]["R2"]
        self.assertEqual(len(r2), 1)
        terminal_y = r2[0]["point_um"][1]
        output = self.data["output_pair"]
        for side in ("p", "n"):
            center_y = output[f"load_{side}_center"][1]
            self.assertAlmostEqual(output[f"load_{side}"][1], center_y + terminal_y)
            self.assertEqual(output["routes"][side][0]["from"], output[f"load_{side}"])

    def test_measured_pcells_fit_reserved_zones(self) -> None:
        report = validate_cell_fit(self.data, self.dimensions)
        self.assertEqual(report["status"], "pass", report["errors"])


if __name__ == "__main__":
    unittest.main()
