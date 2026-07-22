import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "v2/layout/control_routing_checkpoint.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checkpoint = json.loads(CHECKPOINT.read_text())

    def assert_frozen_file(self, record: dict) -> None:
        path = ROOT / record["path"]
        self.assertTrue(path.is_file(), f"missing frozen evidence: {path}")
        self.assertEqual(record["sha256"], sha256(path), str(path))

    def test_every_frozen_release_evidence_hash_matches_disk(self) -> None:
        self.assert_frozen_file(self.checkpoint["gds"])
        self.assert_frozen_file({
            "path": self.checkpoint["magic"]["drc_log"],
            "sha256": self.checkpoint["magic"]["drc_log_sha256"],
        })
        self.assert_frozen_file({
            "path": self.checkpoint["magic"]["extraction_log"],
            "sha256": self.checkpoint["magic"]["extraction_log_sha256"],
        })
        self.assert_frozen_file({
            "path": self.checkpoint["klayout_full_deck_delta"]["report"],
            "sha256": self.checkpoint["klayout_full_deck_delta"]["report_sha256"],
        })
        for report in self.checkpoint["topology_reports"].values():
            self.assert_frozen_file(report)
        self.assert_frozen_file({
            "path": self.checkpoint["distributed_rc"]["report"],
            "sha256": self.checkpoint["distributed_rc"]["report_sha256"],
        })
        for image in self.checkpoint["review_images"]:
            self.assert_frozen_file(image)

    def test_datasheet_is_bound_to_the_candidate_and_keeps_release_blockers(self) -> None:
        datasheet = (ROOT / "v2/docs/datasheet.md").read_text()
        readme = (ROOT / "v2/README.md").read_text()
        frozen_hash = self.checkpoint["gds"]["sha256"]
        self.assertGreaterEqual(datasheet.count(frozen_hash), 2)
        self.assertIn("post-layout analog/phase-code simulation", datasheet)
        self.assertIn("official TinyTapeout", datasheet)
        self.assertIn("not a measured-silicon datasheet", datasheet)
        self.assertIn("detailed engineering datasheet", readme)

    def test_only_the_unified_route_plan_is_active(self) -> None:
        active = json.loads(
            (ROOT / "v2/layout/control_openroad_route_plan.json").read_text()
        )
        self.assertEqual(
            active["status"],
            "production unified-control detailed-route contract with reviewed trim-route optimization",
        )
        self.assertEqual(active["expected_route_count"], 206)
        for filename in (
            "control_internal_route_plan.json",
            "control_external_route_plan.json",
            "control_direct_boundary_route_plan.json",
            "control_service_route_plan.json",
        ):
            plan = json.loads((ROOT / "v2/layout" / filename).read_text())
            self.assertTrue(plan["status"].startswith("retired historical"), filename)
            self.assertEqual(
                plan["superseded_by"], "v2/layout/control_openroad_route_plan.json"
            )


if __name__ == "__main__":
    unittest.main()
