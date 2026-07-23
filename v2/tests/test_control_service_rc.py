import json
import tempfile
import unittest
from pathlib import Path

from v2.tools.generate_control_final_rc_attributes import generate
from v2.tools.generate_rc_force_attributes import DEFAULT_ROUTES
from v2.tools.check_control_service_rc import equivalence_alias_coverage


ROOT = Path(__file__).resolve().parents[2]


class ControlServiceRcTest(unittest.TestCase):
    def test_final_rc_report_covers_every_control_analog_and_supply_route(self) -> None:
        report = json.loads(
            (ROOT / "build/v2/control_routing/final_rc/coverage_audit.json").read_text()
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["required_control_route_count"], 206)
        self.assertEqual(report["required_analog_route_count"], 47)
        self.assertEqual(report["required_routed_net_count"], 254)
        self.assertEqual(report["covered_routed_net_count"], 254)

    def test_final_attributes_cover_control_analog_and_power_drive_points(self) -> None:
        allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        jobs = json.loads(
            (ROOT / "build/v2/control_routing/openroad/openroad_jobs.json").read_text()
        )
        power = json.loads((ROOT / "build/v2/control_power/control_power_geometry.json").read_text())
        control = json.loads(
            (ROOT / "build/v2/control_routing/openroad_route_geometry.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "force.tcl"
            counts = generate(
                allocation, jobs, power, control, list(DEFAULT_ROUTES), output
            )
            self.assertEqual(counts, {
                "analog_routes": 31,
                "control_routes": 206,
                "external_inputs": 13,
                "external_supplies": 2,
                "total_points": 252,
            })
            text = output.read_text()
            self.assertEqual(text.count("label {res:force@}"), 244)
            self.assertEqual(text.count("label {res:drive@}"), 46)
            external_inputs = {
                item["net"] for item in allocation["nets"]
                if any(endpoint["kind"] == "external_top_pin"
                       for endpoint in item["endpoints"])
            }
            for net in external_inputs:
                self.assertIn(f"force external input {net}", text)
            for net in {"VDPWR", "VGND"}:
                self.assertIn(f"force external supply {net}", text)
            for net in ("ch0_input", "ch3_lon", "phase_270", "vcm"):
                self.assertIn(f"force critical analog route {net}", text)
            for label in ("R025", "R030", "R038", "R157"):
                self.assertIn(f"retain routed control mesh {label}", text)
            for net in ("sum_p", "sum_n"):
                section = text.split(f"force critical analog route {net}", 1)[1]
                section = section.split("# force", 1)[0]
                self.assertIn("label {res:force@}", section)
                self.assertIn("label {res:drive@}", section)

    def test_equivalent_bulk_alias_proves_ground_rc_coverage(self) -> None:
        rc = {
            "R": [["R1", "sky130_fd_sc_hd__fill_1_3.VNB", "sky130_fd_sc_hd__fill_1_3.VNB.n0", "1.0"]],
            "C": [],
            "X": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            top_ext = Path(directory) / "top.ext"
            top_ext.write_text(
                'equiv "sky130_fd_sc_hd__fill_1_3.VNB" '
                '"v2_control_power_overlay_0.VGND"\n'
            )
            proof = equivalence_alias_coverage(top_ext, rc, ["VGND"])
        self.assertEqual(
            proof["VGND"]["source_extracted_node"],
            "v2_control_power_overlay_0.VGND",
        )
        self.assertEqual(
            proof["VGND"]["resistor_graph_alias"],
            "sky130_fd_sc_hd__fill_1_3.VNB",
        )

    def test_unrelated_resistor_does_not_cover_ground(self) -> None:
        rc = {
            "R": [["R1", "unrelated", "unrelated.n0", "1.0"]],
            "C": [],
            "X": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            top_ext = Path(directory) / "top.ext"
            top_ext.write_text(
                'equiv "sky130_fd_sc_hd__fill_1_3.VNB" '
                '"v2_control_power_overlay_0.VGND"\n'
            )
            proof = equivalence_alias_coverage(top_ext, rc, ["VGND"])
        self.assertNotIn("VGND", proof)


if __name__ == "__main__":
    unittest.main()
