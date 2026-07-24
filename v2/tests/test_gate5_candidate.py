import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_gate5_candidate import audit


class Gate5CandidateTests(unittest.TestCase):
    def test_frozen_candidate_gate_passes_with_explicit_noise_residual(self) -> None:
        report = audit(ROOT)
        self.assertEqual(
            report["status"],
            "pass_with_documented_noise_residual",
            report["errors"],
        )
        self.assertGreaterEqual(report["metrics"]["mismatch_seed_count"], 60)
        self.assertGreaterEqual(
            report["metrics"]["mismatch_zero_failure_95pct_lower_bound"], 0.95
        )
        contract = json.loads((ROOT / "v2/layout/vcm_varactor_eco.json").read_text())
        self.assertEqual(
            report["frozen_gds_sha256"],
            contract["output_checkpoint"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
