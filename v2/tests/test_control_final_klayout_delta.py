import json
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlFinalKlayoutDeltaTest(unittest.TestCase):
    def test_final_eco_adds_only_classified_varactor_pcell_markers(self) -> None:
        report = json.loads(
            (ROOT / "build/v2/control_routing/direct/final_klayout_delta_audit.json")
            .read_text()
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["added_marker_count"], 10)
        self.assertEqual(report["removed_marker_count"], 0)
        self.assertEqual(report["source_marker_count"], 2770)
        self.assertEqual(report["candidate_marker_count"], 2780)
        self.assertEqual(report["added_category_counts"], {"ct.2": 10})
        self.assertEqual(
            report["expected_added_category_counts"], {"ct.2": 10}
        )
        self.assertTrue(report["reports_newer_than_checked_gds"])
        candidate = ROOT / report["candidate_gds"]
        self.assertEqual(
            report["candidate_gds_sha256"],
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
        )
        expected = dict(report["source_category_counts"])
        expected["ct.2"] += 10
        self.assertEqual(report["candidate_category_counts"], expected)


if __name__ == "__main__":
    unittest.main()
