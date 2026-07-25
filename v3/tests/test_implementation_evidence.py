#!/usr/bin/env python3
"""Keep the V3 implementation checkpoint tied to its exact source inputs."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "v3/evidence/implementation_checkpoint.json"


class ImplementationEvidenceTests(unittest.TestCase):
    def test_checkpoint_source_hashes_are_current(self) -> None:
        report = json.loads(EVIDENCE.read_text())
        for relative, expected in report["source_sha256"].items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
        for relative, expected in report["evidence_artifact_sha256"].items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)

    def test_checkpoint_is_not_mislabeled_as_release_signoff(self) -> None:
        report = json.loads(EVIDENCE.read_text())
        self.assertIn("not layout or release signoff", report["status"])
        self.assertEqual(report["remaining_before_floorplan"], [])
        self.assertTrue(report["remaining_before_release"])
        self.assertTrue(report["layout_authorized"])
        self.assertFalse(report["gds_authorized"])

    def test_exhaustive_prelayout_contract_is_recorded(self) -> None:
        report = json.loads(EVIDENCE.read_text())
        self.assertEqual(report["transition_gate"]["ordered_transition_count"], 56)
        self.assertEqual(report["spur_and_noise_gate"]["phase_state_count"], 8)
        self.assertTrue(
            report["mismatch_gate"]["codebook_is_independently_selected_per_die"]
        )
        self.assertEqual(
            report["spur_and_noise_gate"]["periodic_noise_status"],
            "pass_by_crosschecked_transient_noise_equivalent",
        )
        self.assertEqual(
            report["spur_and_noise_gate"]["periodic_noise_state_count"], 8
        )
        self.assertGreaterEqual(
            report["spur_and_noise_gate"]["periodic_noise_seed_count_per_state"],
            4,
        )


if __name__ == "__main__":
    unittest.main()
