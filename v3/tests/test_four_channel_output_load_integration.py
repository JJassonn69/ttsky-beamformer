from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_output_load_integration import build  # noqa: E402


class FourChannelOutputLoadIntegrationTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_uses_only_current_top(self) -> None:
        manifest = json.loads(
            (ROOT / "v3/layout/four_channel_output_load_integration.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest, build())
        current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        upstream = current["frozen_stage_inputs"]["four_channel_output_load_integration"]
        self.assertEqual(manifest["source"]["gds"], upstream["gds"])
        self.assertEqual(manifest["source"]["gds_sha256"], upstream["gds_sha256"])
        self.assertLess(manifest["matching"]["metric_mismatch_percent"], 1.0)
        self.assertTrue(all(route["direction_reversals"] == 0 for route in manifest["routes"].values()))

    def test_exact_output_integration_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_output_load_integration_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["output_terminal_hits"], {"combined_n": 121, "combined_p": 122})
        self.assertEqual(report["mixer_plus_load_terminal_hits"], {"combined_n": 121, "combined_p": 121})

    def test_distributed_output_rc_gate_is_closed(self) -> None:
        report = json.loads(
            (ROOT / "v3/evidence/four_channel_output_load_rc.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        metrics = report["differential_metrics"]
        self.assertLess(metrics["maximum_route_resistance_mismatch_percent"], 1.0)
        self.assertLess(metrics["total_effective_capacitance_mismatch_percent_typical"], 1.0)
        self.assertLess(metrics["estimated_tau_mismatch_percent_typical"], 1.0)


if __name__ == "__main__":
    unittest.main()
