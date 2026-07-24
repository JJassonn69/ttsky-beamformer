import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from generate_control_openroad_overlay import direct_gds, generate, magic_tcl, snap
from assemble_control_placement_gds import records, split_library, structure_name
from assemble_control_power_gds import text_elements, STRING


class ControlOpenroadOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(
            (ROOT / "v2/layout/control_openroad_route_plan.json").read_text()
        )
        cls.geometry = generate(cls.plan, ROOT)

    def test_all_audited_routes_are_reproduced(self):
        self.assertEqual(self.geometry["counts"]["routes"], 206)
        self.assertEqual(self.geometry["counts"]["labels"], 206)
        self.assertEqual(self.geometry["counts"]["vias"], 1478)
        self.assertEqual(self.geometry["counts"]["patches"], 3)
        self.assertEqual(self.geometry["counts"]["by_layer"]["met4"], 39)
        self.assertNotIn("met5", self.geometry["counts"]["by_layer"])
        self.assertEqual(len({item["net"] for item in self.geometry["routes"]}), 206)
        labels = {item["gds_label"] for item in self.geometry["routes"]}
        self.assertEqual(labels, {f"R{index:03d}" for index in range(206)})
        self.assertTrue(all("/" not in name for name in labels))
        self.assertEqual(set(self.geometry["label_net_map"]), labels)
        self.assertEqual(set(self.geometry["label_net_map"].values()), {
            item["net"] for item in self.geometry["routes"]
        })
        top_pins = [
            item for item in self.geometry["shapes"]
            if item["kind"] == "openroad_top_pin"
        ]
        self.assertEqual(len(top_pins), 45)
        self.assertTrue(all(
            (item["bbox_um"][2] - item["bbox_um"][0])
            * (item["bbox_um"][3] - item["bbox_um"][1]) > 0.240
            for item in top_pins
        ))

    def test_route_grid_snap_does_not_move_legal_five_nanometer_edges(self):
        self.assertEqual(snap(186.145), 186.145)
        self.assertEqual(snap(205.078), 205.080)

    def test_magic_writer_is_routes_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.tcl"
            magic_tcl(self.geometry, path)
            text = path.read_text()
        self.assertIn("CONTROL_OPENROAD_OVERLAY_DRC_COUNT", text)
        self.assertIn("gds write v2_control_openroad_routes.gds", text)
        self.assertIn("label {R000}", text)
        self.assertNotIn("label {global/", text)
        self.assertNotIn("gds read", text)
        self.assertNotIn("sky130_fd_sc_hd__", text)

    def test_direct_gds_is_exact_and_deterministic(self):
        source = ROOT / self.geometry["source_checkpoint"]["gds"]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.gds"
            second = Path(directory) / "second.gds"
            first_report = direct_gds(self.geometry, source, first)
            second_report = direct_gds(self.geometry, source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_report["output_sha256"], second_report["output_sha256"])
            stream = records(first.read_bytes())
            _, structures, _ = split_library(stream)
            self.assertEqual([structure_name(item) for item in structures], [
                "v2_control_openroad_routes"
            ])
            labels = text_elements(structures[0])
            names = {
                next(
                    record[4:].rstrip(b"\0").decode("ascii")
                    for record in element if record[2] == STRING
                )
                for element in labels
            }
            self.assertEqual(names, {f"R{index:03d}" for index in range(206)})
            self.assertEqual(first_report["boundary_count"], 6085)
            self.assertEqual(first_report["label_count"], 206)


if __name__ == "__main__":
    unittest.main()
