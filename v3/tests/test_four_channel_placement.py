from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_placement import build  # noqa: E402


class FourChannelPlacementTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_uses_only_the_frozen_macro(self) -> None:
        path = ROOT / "v3/layout/four_channel_placement.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build())
        self.assertEqual(len(manifest["instances"]), 4)
        self.assertTrue(manifest["placement_strategy"]["input_axes_are_pad_aligned"])
        self.assertEqual(manifest["placement_strategy"]["inter_macro_gaps_um"], [0.0, 0.0, 0.0])
        self.assertFalse(manifest["constraints"]["macro_mutation_allowed"])
        self.assertFalse(manifest["constraints"]["shared_routing_added_in_this_stage"])

    def test_input_ports_land_on_the_four_analog_pin_axes(self) -> None:
        manifest = build()
        for instance in manifest["instances"]:
            input_x = instance["ports"]["element_input"]["at_um"][0]
            self.assertEqual(input_x, instance["ports"]["element_input"]["at_um"][0])
            expected = {0: 152.26, 1: 132.94, 2: 113.62, 3: 94.3}[instance["channel"]]
            self.assertEqual(input_x, expected)

    def test_exact_placement_gate_is_closed_when_generated_artifacts_are_present(self) -> None:
        evidence = ROOT / "v3/evidence/four_channel_placement_gate.json"
        if not evidence.exists():
            self.skipTest("four-channel physical gate has not been generated")
        report = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["device_count"], 1292)


if __name__ == "__main__":
    unittest.main()
