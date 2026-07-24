import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_trim_routes import validate
from generate_control_trim_routes import direct_gds, generate


class ControlTrimRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry = json.loads(
            (ROOT / "build/v2/control_routing/trim_geometry.json").read_text()
        )
        cls.plan = json.loads((ROOT / "v2/layout/control_signal_plan.json").read_text())
        cls.route_plan = json.loads(
            (ROOT / "v2/layout/control_trim_route_plan.json").read_text()
        )
        cls.power_geometry = json.loads(
            (ROOT / "build/v2/control_power/control_power_geometry.json").read_text()
        )
        cls.allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )

    def test_geometry_is_deterministic_and_audited(self) -> None:
        self.assertEqual(
            generate(self.route_plan, self.allocation, ROOT), self.geometry
        )
        report = validate(
            self.geometry, self.plan, self.power_geometry, self.allocation
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["route_count"], 16)
        self.assertEqual(report["via_ownership_error_count"], 0)
        self.assertEqual(report["cross_net_spacing_error_count"], 0)
        self.assertEqual(report["signal_power_spacing_error_count"], 0)
        self.assertEqual(report["reserved_service_pin_count"], 97)
        self.assertEqual(report["service_access_keepout_error_count"], 0)
        self.assertEqual(report["metal4_shape_count"], 0)

    def test_removed_via_landing_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        victim = next(item for item in geometry["shapes"] if item["layer"] == "via2")
        geometry["shapes"].remove(victim)
        report = validate(
            geometry, self.plan, self.power_geometry, self.allocation
        )
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["cut_count_by_layer"]["via2"], 31)

    def test_oversized_trim_cut_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        cut = next(item for item in geometry["shapes"] if item["layer"] == "via2")
        x0, y0, _x1, _y1 = cut["bbox_um"]
        cut["bbox_um"] = [x0, y0, x0 + .40, y0 + .40]
        report = validate(
            geometry, self.plan, self.power_geometry, self.allocation
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("must be one 0.20x0.20" in item for item in report["errors"]))

    def test_route_over_reserved_service_landing_is_rejected(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        service = next(
            endpoint
            for record in self.allocation["nets"]
            if record["class"] == "service_tree"
            for endpoint in record["endpoints"]
            if endpoint.get("kind") == "standard_cell_pin"
            and endpoint.get("region") == "trim_configuration_bank"
        )
        x, y = service["point_um"]
        victim = next(
            item for item in geometry["shapes"]
            if item["layer"] == "metal2"
            and item["kind"] == "monotonic_trim_bus"
        )
        victim["bbox_um"] = [x - .16, y - .16, x + .16, y + .16]
        report = validate(
            geometry, self.plan, self.power_geometry, self.allocation
        )
        self.assertEqual(report["status"], "fail")
        self.assertGreater(report["service_access_keepout_error_count"], 0)

    def test_authoritative_trim_gds_is_direct_and_deterministic(self) -> None:
        layer_names = {"metal2": "met2", "via2": "via2", "metal3": "met3"}
        data = {
            **self.geometry,
            "shapes": [
                {**item, "layer": layer_names[item["layer"]]}
                for item in self.geometry["shapes"]
            ],
            "labels": [
                {**item, "layer": layer_names[item["layer"]], "gds_label": item["net"]}
                for item in self.geometry["labels"]
            ],
        }
        source = ROOT / self.geometry["source_checkpoint"]["gds"]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.gds"
            second = Path(directory) / "second.gds"
            first_report = direct_gds(data, source, first)
            second_report = direct_gds(data, source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_report["output_sha256"], second_report["output_sha256"])
            self.assertEqual(first_report["boundary_count"], 128)
            self.assertEqual(first_report["label_count"], 16)


if __name__ == "__main__":
    unittest.main()
