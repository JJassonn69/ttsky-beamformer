import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = ROOT / "v2"

import sys
sys.path.insert(0, str(V2_ROOT / "tools"))

from generate_support_routes import generate


class SupportRouteGeneratorTests(unittest.TestCase):
    def test_capacitor_and_bias_routes_use_clear_edges(self) -> None:
        plan = json.loads((V2_ROOT / "layout/integration_plan.json").read_text())
        dimensions = json.loads((V2_ROOT / "layout/pcell_dimensions.json").read_text())
        catalog = json.loads((V2_ROOT / "layout/port_catalog.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(plan, dimensions, catalog, output)
            text = output.read_text()
        self.assertEqual(metrics["c2_external_transition"], [28.18, 116.5])
        self.assertAlmostEqual(metrics["vbias_symmetry_axis_x"], 172.105)
        self.assertIn("# CVCM.C1 -> vcm", text)
        self.assertIn("paint_rect metal4 40.6800 129.8000 41.0800 130.2000", text)
        c1_block = text.split("# CVCM.C1 -> vcm", 1)[1].split("# CVCM.C2", 1)[0]
        self.assertNotIn("paint_rect via3", c1_block)
        self.assertIn("paint_rect via3 27.9800 116.3000 28.3800 116.7000", text)
        self.assertIn("SUPPORT_ROUTE_DRC_COUNT", text)

    def test_bias_pair_is_routed_symmetrically(self) -> None:
        plan = json.loads((V2_ROOT / "layout/integration_plan.json").read_text())
        dimensions = json.loads((V2_ROOT / "layout/pcell_dimensions.json").read_text())
        catalog = json.loads((V2_ROOT / "layout/port_catalog.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(plan, dimensions, catalog, output)
        self.assertAlmostEqual(metrics["vbias_symmetry_axis_x"], 172.105)
        self.assertAlmostEqual(metrics["ground_symmetry_axis_x"], 173.0)
        self.assertGreater(metrics["bias_drain_y"], metrics["bias_source_y"])


if __name__ == "__main__":
    unittest.main()
