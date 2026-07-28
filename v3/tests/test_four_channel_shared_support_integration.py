from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_shared_support_integration import build  # noqa: E402


class FourChannelSharedSupportIntegrationTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_hash_binds_both_blocks(self) -> None:
        path = ROOT / "v3/layout/four_channel_shared_support_integration.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build())
        self.assertEqual(set(manifest["blocks"]), {"vcm", "tail_bias"})
        self.assertEqual(manifest["tree_roots_um"], {"ref": [125.68, 161.2], "vbias": [123.98, 159.0]})
        self.assertEqual(manifest["via3_points_um"], [[53.0, 90.0]])

    def test_exact_support_integration_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_shared_support_integration_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["shared_terminal_hits"], {"ref": 69, "vbias": 79})


if __name__ == "__main__":
    unittest.main()
