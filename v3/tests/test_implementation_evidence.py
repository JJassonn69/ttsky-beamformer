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

    def test_checkpoint_is_not_mislabeled_as_release_signoff(self) -> None:
        report = json.loads(EVIDENCE.read_text())
        self.assertIn("not layout or release signoff", report["status"])
        self.assertTrue(report["remaining_before_floorplan"])


if __name__ == "__main__":
    unittest.main()
