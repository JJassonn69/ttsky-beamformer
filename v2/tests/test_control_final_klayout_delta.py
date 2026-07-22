import json
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlFinalKlayoutDeltaTest(unittest.TestCase):
    def test_final_routes_add_no_foundry_deck_markers(self) -> None:
        report = json.loads(
            (ROOT / "build/v2/control_routing/direct/final_klayout_delta_audit.json")
            .read_text()
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["added_marker_count"], 0)
        self.assertEqual(report["removed_marker_count"], 0)
        self.assertEqual(report["candidate_marker_count"], 2776)
        self.assertTrue(report["reports_newer_than_checked_gds"])
        candidate = ROOT / report["candidate_gds"]
        self.assertEqual(
            report["candidate_gds_sha256"],
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            report["candidate_category_counts"], report["source_category_counts"]
        )


if __name__ == "__main__":
    unittest.main()
