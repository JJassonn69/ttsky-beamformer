from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from generate_output_summing_routes import generate


class OutputSummingRouteGeneratorTests(unittest.TestCase):
    def test_p_n_trees_and_pad_routes_are_layer_matched(self) -> None:
        floorplan = json.loads((ROOT / "v2/layout/floorplan.json").read_text())
        routing = json.loads((ROOT / "v2/layout/routing_plan.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(floorplan, routing, output)
            text = output.read_text()

        p, n = metrics["sum_p"], metrics["sum_n"]
        for key in (
            "aggregate_tree_m3_centerline_um",
            "aggregate_tree_m4_centerline_um",
            "load_to_pad_m3_centerline_um",
            "load_to_pad_m4_centerline_um",
            "tree_via3_sites",
            "pad_route_via3_sites",
        ):
            self.assertAlmostEqual(p[key], n[key], msg=key)
        for values in (p, n):
            paths = list(values["source_to_load_centerline_um"].values())
            self.assertAlmostEqual(max(paths), min(paths))
        self.assertIn("label {sum_p}", text)
        self.assertIn("label {sum_n}", text)
        self.assertNotIn("metal5", text)


if __name__ == "__main__":
    unittest.main()
