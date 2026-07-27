from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from assert_current_channel import audit_generated_build_entries, validate_channel  # noqa: E402


class CurrentChannelFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))

    def test_frozen_channel_and_evidence_are_hash_bound(self) -> None:
        gds = ROOT / self.current["gds"]
        spice = ROOT / self.current["flat_spice"]
        self.assertEqual(hashlib.sha256(gds.read_bytes()).hexdigest(), self.current["gds_sha256"])
        self.assertEqual(
            hashlib.sha256(spice.read_bytes()).hexdigest(),
            self.current["flat_spice_sha256"],
        )
        self.assertEqual(validate_channel()["status"], "pass")
        for key in ("physical_topology", "distributed_rc", "direct_gds_precheck"):
            evidence = json.loads(
                (ROOT / self.current["signoff_evidence"][key]).read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["status"], "pass", key)

    def test_noncurrent_gds_is_rejected(self) -> None:
        source = ROOT / self.current["gds"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "candidate.gds"
            candidate.write_bytes(source.read_bytes() + b"not-current")
            with self.assertRaisesRegex(RuntimeError, "refusing non-current"):
                validate_channel(candidate)

    def test_generated_build_directory_contains_only_registered_entries(self) -> None:
        self.assertEqual(
            audit_generated_build_entries(),
            sorted(self.current["active_generated_build_entries"]),
        )


if __name__ == "__main__":
    unittest.main()
