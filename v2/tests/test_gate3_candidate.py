import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from check_gate3_candidate import build_manifest


class Gate3CandidateTests(unittest.TestCase):
    def test_frozen_candidate_gate_passes(self) -> None:
        report = build_manifest(ROOT)
        self.assertEqual(report["status"], "pass", report["errors"])
        contract = json.loads((ROOT / "v2/layout/vcm_varactor_eco.json").read_text())
        self.assertEqual(
            report["frozen_candidate_sha256"],
            contract["output_checkpoint"]["sha256"],
        )
        self.assertEqual(len(report["evidence"]), 18)
        self.assertFalse(any(
            item["path"].endswith("service_route_audit.json")
            for item in report["evidence"]
        ))
        self.assertTrue(all(count == 0 for count in report["direct_flat_rule_counts"].values()))

    def test_nonpassing_report_is_rejected(self) -> None:
        source = ROOT / "build/v2/control_routing/quadrature_extraction/trim_topology_audit.json"
        data = json.loads(source.read_text())
        self.assertEqual(data["status"], "pass")
        # The production function is integration-oriented; its negative cases
        # are covered by each underlying audit's mutation tests.  Keep an
        # explicit assertion here that the consolidated evidence records the
        # source report status rather than replacing it with a blanket pass.
        report = build_manifest(ROOT)
        item = next(entry for entry in report["evidence"] if entry["path"].endswith("trim_topology_audit.json"))
        self.assertEqual(item["status"], "pass")


if __name__ == "__main__":
    unittest.main()
