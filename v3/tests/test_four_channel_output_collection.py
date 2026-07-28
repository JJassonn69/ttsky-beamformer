from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_output_collection import build  # noqa: E402


class FourChannelOutputCollectionTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_balanced(self) -> None:
        path = ROOT / "v3/layout/four_channel_output_collection.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build())
        p_tree = manifest["trees"]["p"]
        n_tree = manifest["trees"]["n"]
        self.assertAlmostEqual(
            n_tree["source_to_root_length_um"] - p_tree["source_to_root_length_um"],
            manifest["routing_decisions"]["p_root_compensation_required_um"],
            places=9,
        )
        self.assertEqual(p_tree["route_layer"], "metal3")
        self.assertEqual(n_tree["route_layer"], "metal3")
        self.assertEqual(len(p_tree["via2_points_um"]), 4)
        self.assertEqual(len(p_tree["via3_points_um"]), 0)
        self.assertEqual(len(n_tree["via2_points_um"]), 4)
        self.assertEqual(len(n_tree["via3_points_um"]), 0)

    def test_exact_output_collection_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_output_collection_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["combined_terminal_hits"]["combined_p_internal"], 120)
        self.assertEqual(report["combined_terminal_hits"]["combined_n_internal"], 120)


if __name__ == "__main__":
    unittest.main()
