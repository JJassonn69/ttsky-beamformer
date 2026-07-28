from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DigitalOutputTieFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/digital_output_tie_gate.json").read_text(encoding="utf-8")
        )
        self.frozen = ROOT / "v3/frozen/digital_output_tie"

    def test_frozen_output_tie_remains_exact_submission_upstream(self) -> None:
        top = self.current["current_top_level"]
        submission = json.loads(
            (ROOT / "v3/evidence/submission_gate.json").read_text(encoding="utf-8")
        )
        self.assertEqual(top["physical_gate"], "v3/evidence/submission_gate.json")
        self.assertEqual(top["gds_sha256"], sha256(ROOT / top["gds"]))
        self.assertEqual(top["flat_spice_sha256"], sha256(ROOT / top["flat_spice"]))
        self.assertEqual(self.gate["gds_sha256"], sha256(ROOT / self.gate["gds"]))
        self.assertEqual(
            self.gate["flat_spice_sha256"], sha256(ROOT / self.gate["flat_spice"])
        )
        self.assertTrue(
            submission["physical_signoff"]["physical_stage_gates"]
            ["digital_output_tie_gate.json"]["status"] == "pass"
        )
        self.assertEqual(submission["gds_sha256"], top["gds_sha256"])

    def test_geometry_topology_and_precheck_are_closed(self) -> None:
        geometry = json.loads((self.frozen / "route_geometry.json").read_text(encoding="utf-8"))
        topology = json.loads((self.frozen / "topology_audit.json").read_text(encoding="utf-8"))
        precheck = json.loads((self.frozen / "precheck_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(geometry["counts"]["pins"], 24)
        self.assertEqual(geometry["counts"]["vertical_drops"], 24)
        self.assertEqual(geometry["counts"]["vias"], 0)
        self.assertEqual(topology["status"], "pass")
        self.assertTrue(topology["checks"]["all_outputs_tied_to_vgnd"])
        self.assertTrue(topology["checks"]["vdpwr_remains_separate"])
        self.assertTrue(topology["checks"]["previous_route_partition_preserved"])
        self.assertEqual(topology["checks"]["previous_signal_labels_tied_to_supply"], [])
        self.assertEqual(topology["checks"]["total_extracted_devices"], 6037)
        self.assertEqual(precheck["status"], "pass")
        self.assertTrue(all(item["markers"] == 0 for item in precheck["checks"].values()))

    def test_frozen_hashes_bind_the_evidence(self) -> None:
        expected = {
            "route_geometry": "route_geometry.json",
            "assembly_report": "assembly_report.json",
            "direct_gds_precheck": "precheck_summary.json",
            "magic_readback_log": "magic_readback.log",
            "extraction_feedback": "extraction_feedback.txt",
            "top_ext": "v3_four_ch_output_tied.ext",
            "overlay_ext": "v3_digital_output_tie_low.ext",
            "topology_audit": "topology_audit.json",
            "overlay_gds": "v3_digital_output_tie_low.gds",
            "integrated_review_image": "01_integrated_output_ties.png",
            "overlay_review_image": "02_output_tie_overlay_only.png",
            "terminal_review_image": "03_exact_output_pin_drops.png",
        }
        for key, filename in expected.items():
            self.assertEqual(sha256(self.frozen / filename), self.gate["sha256"][key])


if __name__ == "__main__":
    unittest.main()
