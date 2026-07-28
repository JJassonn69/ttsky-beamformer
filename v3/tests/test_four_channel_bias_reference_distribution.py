from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_bias_reference_distribution import build  # noqa: E402


class FourChannelBiasReferenceDistributionTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_each_tree_is_balanced(self) -> None:
        path = ROOT / "v3/layout/four_channel_bias_reference_distribution.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build())
        self.assertEqual(set(manifest["trees"]), {"ref", "vbias"})
        self.assertEqual(manifest["trees"]["vbias"]["source_to_root_length_um"], 44.07)
        self.assertEqual(manifest["trees"]["ref"]["source_to_root_length_um"], 47.27)
        for tree in manifest["trees"].values():
            self.assertTrue(tree["equal_length_to_all_four_channels"])
            self.assertEqual(len(tree["source_points_um"]), 4)
            self.assertEqual(len(tree["via2_points_um"]), 4)
            self.assertEqual(len(tree["via3_points_um"]), 8)

    def test_exact_distribution_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_bias_reference_distribution_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["shared_terminal_hits"], {"ref": 64, "vbias": 60})


if __name__ == "__main__":
    unittest.main()
