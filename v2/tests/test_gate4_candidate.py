import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_gate4_candidate import EXPECTED_CASES, MANIFEST, audit


class Gate4CandidateTests(unittest.TestCase):
    def test_frozen_candidate_gate_passes(self) -> None:
        report = audit(ROOT)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["case_count"], 10)
        contract = json.loads((ROOT / "v2/layout/vcm_varactor_eco.json").read_text())
        self.assertEqual(
            report["frozen_gds_sha256"],
            contract["output_checkpoint"]["sha256"],
        )

    def test_missing_case_is_rejected(self) -> None:
        manifest = json.loads((ROOT / MANIFEST).read_text())
        mutated = copy.deepcopy(manifest)
        mutated["cases"].pop(next(iter(EXPECTED_CASES)))
        report = audit(ROOT, mutated)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("case set differs" in error for error in report["errors"]))

    def test_stale_netlist_is_rejected(self) -> None:
        manifest = json.loads((ROOT / MANIFEST).read_text())
        mutated = copy.deepcopy(manifest)
        mutated["expected_netlist_sha256"]["rc"] = "stale"
        report = audit(ROOT, mutated)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("stale extracted netlists" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
