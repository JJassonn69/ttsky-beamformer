import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_control_power import validate
from generate_control_power import generate, magic_tcl


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ControlPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ROOT / "v2/layout/control_power_plan.json").read_text())
        cls.placement = json.loads(
            (ROOT / "build/v2/control_placement/control_placement.json").read_text()
        )
        cls.integration = json.loads((ROOT / "v2/layout/integration_plan.json").read_text())
        cls.dimensions = json.loads((ROOT / "v2/layout/pcell_dimensions.json").read_text())
        cls.catalog = json.loads((ROOT / "v2/layout/port_catalog.json").read_text())
        cls.geometry_path = ROOT / "build/v2/control_power/control_power_geometry.json"
        cls.geometry = json.loads(cls.geometry_path.read_text())

    def test_generated_geometry_is_deterministic(self) -> None:
        source = ROOT / self.plan["source_checkpoint"]["gds"]
        if sha256(source) == self.plan["source_checkpoint"]["sha256"]:
            result = generate(
                self.plan, self.placement, self.integration, self.dimensions,
                self.catalog, source,
            )
            self.assertEqual(result, self.geometry)
            return

        # This pre-route stage is a frozen input to the authoritative unified
        # route. Its historical placement source was later regenerated, so
        # trying to rebuild it now would silently create a different lineage.
        self.assertTrue(
            self.plan["regeneration_policy"].startswith("frozen_artifact_only")
        )
        geometry = self.plan["geometry_checkpoint"]
        powered = self.plan["powered_gds_checkpoint"]
        self.assertEqual(sha256(ROOT / geometry["path"]), geometry["sha256"])
        self.assertEqual(sha256(ROOT / powered["path"]), powered["sha256"])
        active = json.loads(
            (ROOT / "v2/layout/control_openroad_route_plan.json").read_text()
        )
        self.assertEqual(active["source_checkpoint"]["sha256"], powered["sha256"])

    def test_every_rail_has_two_upper_contacts_and_one_net_component(self) -> None:
        report = validate(self.plan, self.geometry, self.placement)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["row_rail_count"], 35)
        self.assertEqual(report["upper_contact_count"], 70)
        self.assertEqual(report["fixed_helper_rail_count"], 14)
        self.assertEqual(report["fixed_helper_upper_contact_count"], 28)
        self.assertEqual(report["fixed_helper_nwell_bridge_count"], 16)
        self.assertEqual(
            report["covered_standard_cell_tap_and_filler_power_edges"],
            2 * self.placement["counts"]["total_instances"],
        )
        self.assertEqual(report["net_component_count"], {"VDPWR": 1, "VGND": 1})

    def test_missing_fixed_helper_contact_is_rejected(self) -> None:
        geometry = json.loads(json.dumps(self.geometry))
        geometry["fixed_helper_contacts"].pop()
        report = validate(self.plan, geometry, self.placement)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("fixed-helper rail" in item for item in report["errors"]))

    def test_no_metal5_or_power_shape_in_signal_keepouts(self) -> None:
        report = validate(self.plan, self.geometry, self.placement)
        self.assertEqual(report["metal5_shape_count"], 0)
        self.assertEqual(report["keepout_intersection_count"], 0)
        self.assertEqual(report["cross_net_spacing_violation_count"], 0)

    def test_only_named_m3_source_bridges_cross_the_inner_ground_source(self) -> None:
        bridges = [
            item for item in self.geometry["shapes"]
            if item["kind"] == "required_crossing_bridge"
        ]
        self.assertEqual(len(bridges), 3)
        self.assertTrue(all(item["net"] == "VDPWR" for item in bridges))
        self.assertTrue(all(item["layer"] == "metal3" for item in bridges))
        self.assertTrue(all(item["bbox_um"][0] == 2.0 for item in bridges))
        self.assertTrue(all(item["bbox_um"][2] == 7.0 for item in bridges))

    def test_overlay_writer_contains_no_foundry_macro_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.tcl"
            magic_tcl(self.geometry, path)
            text = path.read_text()
        self.assertIn("CONTROL_POWER_OVERLAY_DRC_COUNT", text)
        self.assertIn("gds write v2_control_power_overlay.gds", text)
        self.assertNotIn("sky130_fd_sc_hd__", text)
        self.assertNotIn("gds read", text)


if __name__ == "__main__":
    unittest.main()
