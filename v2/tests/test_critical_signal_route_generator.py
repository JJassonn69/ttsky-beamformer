from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from generate_critical_signal_routes import generate


class CriticalSignalRouteGeneratorTests(unittest.TestCase):
    def test_equal_dual_branch_lo_without_u_bends(self) -> None:
        def read(name: str) -> dict:
            return json.loads((ROOT / "v2/layout" / name).read_text())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(
                read("floorplan.json"), read("channel_template.json"),
                read("pcell_dimensions.json"), read("port_catalog.json"),
                read("routing_plan.json"), [0], output,
            )
            text = output.read_text()
        self.assertAlmostEqual(metrics["ch0"]["lop_vertical_um"], metrics["ch0"]["lon_vertical_um"])
        self.assertAlmostEqual(metrics["ch0"]["lop_branch_pitch_um"], metrics["ch0"]["lon_branch_pitch_um"])
        self.assertNotIn("dogleg", text.lower())
        self.assertNotIn("u-bend", text.lower())
        self.assertIn("CH0.PBUF_P.X -> ch0_lop", text)
        self.assertIn("CH0.PBUF_N.X -> ch0_lon", text)
        self.assertGreater(text.count("paint_rect viali"), 2)
        self.assertIn("four_channel_placement magic v2_four_channel_placement.gds", text)
        self.assertIn("required clean-placement GDS does not exist", text)
        self.assertIn("clean-placement top cell was not imported", text)

    def test_single_net_probe_uses_production_geometry(self) -> None:
        def read(name: str) -> dict:
            return json.loads((ROOT / "v2/layout" / name).read_text())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            generate(
                read("floorplan.json"), read("channel_template.json"),
                read("pcell_dimensions.json"), read("port_catalog.json"),
                read("routing_plan.json"), [0], output, {"ch0_gm_p"},
            )
            text = output.read_text()
        self.assertIn("GM_SIG_A.D -> ch0_gm_p", text)
        self.assertIn("vertical track gm_p -> ch0_gm_p", text)
        self.assertIn("net label: ch0_gm_p", text)
        self.assertNotIn("GM_REF_A.D -> ch0_gm_n", text)
        self.assertNotIn("net label: ch0_lop", text)

    def test_local_trim_mode_uses_guard_and_monotonic_controls(self) -> None:
        def read(name: str) -> dict:
            return json.loads((ROOT / "v2/layout" / name).read_text())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            generate(
                read("floorplan.json"), read("channel_template.json"),
                read("pcell_dimensions.json"), read("port_catalog.json"),
                read("routing_plan.json"), [0], output, None, True,
            )
            text = output.read_text()
        self.assertIn("sky130::subconn_guard_draw", text)
        self.assertIn("CH0.TMAIN0.D -> ch0_tail", text)
        self.assertIn("CH0.TSW2_ON.G -> ch0_trim_b2", text)
        self.assertIn("CH0.TSW2_OFF.G -> ch0_trim_b2_b", text)
        self.assertIn("CH0.TSW2_OFF.S -> VGND", text)
        self.assertNotIn("ch0_vgnd_local", text)
        self.assertIn("paint_rect via1 148.5250 46.3700 148.7850 46.6300", text)
        self.assertNotIn("paint_rect metal1 148.5400 45.4500 148.7700 46.5000", text)
        self.assertIn("paint_rect metal3 148.6550 46.3000 149.2700 46.7000", text)
        self.assertIn("paint_rect metal1 149.0950 46.3850 149.3950 46.6150", text)
        self.assertIn("paint_rect metal1 149.2800 45.3500 149.5100 46.5000", text)
        self.assertIn("shared analog ground bus -> VGND", text)
        self.assertIn("label {VGND} FreeSans 0.10u -met4", text)
        self.assertIn("cellname rename v2_four_channel_local_routed", text)
        self.assertNotIn("output-crossover bridge", text.lower())


if __name__ == "__main__":
    unittest.main()
