import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "v2/layout/control_routing_checkpoint.json"
LATEST_VALIDATION = ROOT / "v2/evidence/latest_validation.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checkpoint = json.loads(CHECKPOINT.read_text())
        cls.latest = json.loads(LATEST_VALIDATION.read_text())

    def assert_frozen_file(self, record: dict) -> None:
        path = ROOT / record["path"]
        self.assertTrue(path.is_file(), f"missing frozen evidence: {path}")
        self.assertEqual(record["sha256"], sha256(path), str(path))

    def test_every_frozen_release_evidence_hash_matches_disk(self) -> None:
        self.assert_frozen_file(self.checkpoint["gds"])
        self.assert_frozen_file(self.checkpoint["gds"]["pre_varactor_user_route_source"])
        self.assertEqual(self.checkpoint["schema_version"], 7)
        self.assertEqual(self.checkpoint["physical"]["status"], "pass")
        self.assertEqual(self.checkpoint["distributed_rc"]["status"], "pass")
        self.assertGreaterEqual(
            self.checkpoint["electrical"]["gate5"]["mismatch_seed_count"], 60
        )

    def test_datasheet_is_bound_to_the_candidate_and_keeps_release_blockers(self) -> None:
        datasheet = (ROOT / "v2/docs/datasheet.md").read_text()
        readme = (ROOT / "v2/README.md").read_text()
        frozen_hash = self.checkpoint["gds"]["sha256"]
        self.assertGreaterEqual(datasheet.count(frozen_hash), 2)
        self.assertIn("exact distributed-RC 20-case beam codebook", datasheet)
        self.assertIn("60-seed", datasheet)
        self.assertIn("Electrical characterization plots", datasheet)
        self.assertIn("official TinyTapeout", datasheet)
        self.assertIn("not a measured-silicon datasheet", datasheet)
        for filename in (
            "beam-codebook-response.svg",
            "trim-characterization.svg",
            "mismatch-campaign.svg",
            "electrical-sensitivity.svg",
            "two-tone-linearity.svg",
            "cold-start-timing.svg",
        ):
            self.assertIn(filename, datasheet)
        self.assertIn("detailed engineering datasheet", readme)

    def test_compact_validation_record_is_bound_to_tracked_artifacts(self) -> None:
        self.assertEqual(self.latest["candidate"]["sha256"], self.checkpoint["gds"]["sha256"])
        self.assert_frozen_file(self.latest["candidate"])
        self.assert_frozen_file(
            self.latest["candidate"]["pre_varactor_user_route_source"]
        )
        for record in self.latest["submission"].values():
            if isinstance(record, dict) and "path" in record:
                self.assert_frozen_file(record)
        self.assertEqual(self.latest["schema_version"], 3)
        self.assertEqual(
            self.latest["gates"]["physical_gate3"],
            "pass",
        )
        self.assertEqual(
            self.latest["gates"]["bounded_electrical_gate4"],
            "pass",
        )
        self.assertEqual(
            self.latest["gates"]["characterization_gate5"],
            "pass_with_documented_noise_residual",
        )
        for record in self.latest["frozen_evidence"].values():
            self.assert_frozen_file(record)
        self.assertEqual(
            self.latest["visual_review"]["source_gds_sha256"],
            self.checkpoint["gds"]["sha256"],
        )
        self.assertEqual(len(self.latest["visual_review"]["images"]), 2)
        for record in self.latest["visual_review"]["images"]:
            self.assert_frozen_file(record)
        self.assertIn(
            self.latest["release_status"],
            (
                "local_signoff_passed_official_tinytapeout_workflow_pending",
                "fab_ready_research_prototype",
            ),
        )

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
