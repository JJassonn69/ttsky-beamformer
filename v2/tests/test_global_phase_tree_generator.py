from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from generate_global_phase_tree import generate


class GlobalPhaseTreeGeneratorTests(unittest.TestCase):
    def test_all_phases_and_all_leaves_have_identical_topology(self) -> None:
        floorplan = json.loads((ROOT / "v2/layout/floorplan.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "route.tcl"
            metrics = generate(floorplan, output)
            text = output.read_text()

        self.assertEqual(
            set(metrics), {"phase_0", "phase_90", "phase_180", "phase_270"}
        )
        reference = metrics["phase_0"]
        for phase, values in metrics.items():
            self.assertAlmostEqual(
                values["aggregate_m3_centerline_um"],
                reference["aggregate_m3_centerline_um"],
                msg=phase,
            )
            self.assertAlmostEqual(
                values["aggregate_m4_centerline_um"],
                reference["aggregate_m4_centerline_um"],
                msg=phase,
            )
            self.assertEqual(values["via2_sites"], 1)
            self.assertEqual(values["via3_sites"], 9)
            paths = list(values["root_to_leaf_centerline_um"].values())
            self.assertAlmostEqual(max(paths), min(paths), msg=phase)
        self.assertNotIn("metal5", text)
        self.assertNotIn("U-turn", text)


if __name__ == "__main__":
    unittest.main()
