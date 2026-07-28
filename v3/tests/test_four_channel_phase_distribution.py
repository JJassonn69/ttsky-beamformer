from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_phase_distribution import build  # noqa: E402


class FourChannelPhaseDistributionTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_all_sixteen_paths_match(self) -> None:
        path = ROOT / "v3/layout/four_channel_phase_distribution.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build())
        self.assertEqual(len(manifest["trees"]), 4)
        lengths = {
            tree["source_to_root_length_um"] for tree in manifest["trees"].values()
        }
        self.assertEqual(lengths, {37.97})
        self.assertTrue(all(
            tree["equal_length_to_all_four_channels"]
            for tree in manifest["trees"].values()
        ))
        self.assertEqual(sum(len(tree["via3_points_um"]) for tree in manifest["trees"].values()), 16)

    def test_exact_phase_distribution_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_phase_distribution_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(set(report["phase_terminal_hits"].values()), {32})


if __name__ == "__main__":
    unittest.main()
