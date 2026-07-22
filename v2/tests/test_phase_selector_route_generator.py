from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from generate_phase_selector_routes import generate


class PhaseSelectorRouteGeneratorTests(unittest.TestCase):
    def test_mirrored_internal_trees_and_named_anchors(self) -> None:
        def read(name: str) -> dict:
            return json.loads((ROOT / "v2/layout" / name).read_text())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(
                read("floorplan.json"),
                read("channel_template.json"),
                read("pcell_dimensions.json"),
                read("port_catalog.json"),
                [0],
                output,
            )
            text = output.read_text()
        channel = metrics["ch0"]
        self.assertAlmostEqual(
            channel["mux_a_local_m3_um"], channel["mux_b_local_m3_um"]
        )
        self.assertAlmostEqual(
            channel["mux_a_cross_m3_um"], channel["mux_b_cross_m3_um"]
        )
        self.assertAlmostEqual(
            channel["mux_a_cross_m4_um"], channel["mux_b_cross_m4_um"]
        )
        self.assertAlmostEqual(
            channel["mux_a_pin_escape_m2_um"],
            channel["mux_b_pin_escape_m2_um"],
        )
        self.assertIn("PMUX_P.X to PAND_P.A -> ch0_mux_p_out", text)
        self.assertIn("PAND_N.X to PBUF_N.A -> ch0_gate_n", text)
        self.assertIn("label {ch0_phase_0_leaf}", text)
        self.assertIn("label {ch0_phase_enable}", text)
        self.assertIn("paint_rect locali 151.8575 128.5150 152.0275 128.6850", text)
        self.assertIn("paint_rect via2 152.9800 128.5000 153.3800 128.9000", text)
        self.assertNotIn("paint_rect locali 150.9150 129.7350 151.0850 129.9050", text)
        self.assertNotIn("metal5", text)


if __name__ == "__main__":
    unittest.main()
