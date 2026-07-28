import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class NoStaleV1SubmissionReferencesTest(unittest.TestCase):
    def test_active_submission_surface_contains_no_v1_contract(self) -> None:
        paths = [
            ROOT / "README.md",
            ROOT / "docs/info.md",
            ROOT / "docs/datasheet.md",
            ROOT / "docs/presilicon_plan.md",
            ROOT / "info.yaml",
            ROOT / "src/project.v",
            ROOT / "Makefile",
            ROOT / ".github/workflows/gds.yaml",
            ROOT / "submission/template.lock",
            ROOT / "v2/README.md",
            ROOT / "v2/docs/datasheet.md",
            ROOT / "v2/spec/physical_design.md",
            ROOT / "v2/layout/control_routing_checkpoint.json",
            ROOT / "v2/evidence/latest_validation.json",
            ROOT / "v2/evidence/latest_validation.md",
        ]
        forbidden = (
            "8e9d15ed2f30e446a22de38c58fdf172e1cf78b20aa1c8052efc828d56dfb5f4",
            "d9c9aae5771af815833668374924baee23f60a51747c7966e2517dcb6f6a6130",
            "655e6108952e1ac604ed84671ae318a8a2d1e1c7603c7a412edbdad1adcc62a0",
            "tt_analog_1x2.def",
            "CH2_PHASE_180",
            'tiles:        "1x2"',
            "analog_pins:  4",
            "clock_hz:     4000000",
        )
        for path in paths:
            text = path.read_text()
            for token in forbidden:
                self.assertNotIn(token, text, f"{path}: stale token {token}")

    def test_active_submission_directory_has_no_v1_evidence_bundle(self) -> None:
        expected = {"README.md", "template.lock"}
        self.assertEqual(
            {path.name for path in (ROOT / "submission").iterdir() if path.is_file()},
            expected,
        )
        self.assertTrue((ROOT / "legacy/v1/submission/signoff.json").is_file())

    def test_active_gds_workflow_uses_only_v2_release_checks(self) -> None:
        workflow = (ROOT / ".github/workflows/gds.yaml").read_text()
        self.assertIn("v2/tools/generate_submission_gds.py", workflow)
        self.assertIn("v2.tests.test_submission_artifacts", workflow)
        self.assertIn("v2/tools/check_latest_validation.py", workflow)
        self.assertNotIn("discover -s tests", workflow)
        self.assertNotIn("tools/check_gds_flat_rules.py", workflow)


if __name__ == "__main__":
    unittest.main()
