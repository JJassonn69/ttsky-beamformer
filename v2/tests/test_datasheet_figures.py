import hashlib
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "v2/evidence/datasheet_figures.json"
DATASHEET = ROOT / "v2/docs/datasheet.md"
EXPECTED_GDS = "90b51a5f37fd114a8cb24afec32ba1c5364b64f15865f19fe738caa7cb8a994a"
EXPECTED_BASE = "389751fb5a690666b7153770162e36ca4f6b1d2a48500f62d5b9ad2b56353def"
EXPECTED_RC = "4a29c4ecaa4178528c68c9427785236a283171d3cecc1399cf137483c035736a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatasheetFigureEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text())
        cls.datasheet = DATASHEET.read_text()

    def test_manifest_is_bound_to_the_current_candidate(self) -> None:
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["candidate_gds_sha256"], EXPECTED_GDS)
        self.assertEqual(self.manifest["base_netlist_sha256"], EXPECTED_BASE)
        self.assertEqual(self.manifest["distributed_rc_netlist_sha256"], EXPECTED_RC)

    def test_all_six_figures_match_their_frozen_hashes_and_are_embedded(self) -> None:
        self.assertEqual(len(self.manifest["figures"]), 6)
        expected = {
            "beam-codebook-response.svg",
            "trim-characterization.svg",
            "mismatch-campaign.svg",
            "electrical-sensitivity.svg",
            "two-tone-linearity.svg",
            "cold-start-timing.svg",
        }
        actual = set()
        for record in self.manifest["figures"]:
            path = ROOT / record["path"]
            actual.add(path.name)
            self.assertTrue(path.is_file(), path)
            self.assertEqual(record["sha256"], sha256(path), path)
            self.assertEqual(record["bytes"], path.stat().st_size, path)
            root = ET.parse(path).getroot()
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertIn(path.name, self.datasheet)
        self.assertEqual(actual, expected)

    def test_plotted_datasets_retain_characterization_not_only_status(self) -> None:
        datasets = self.manifest["datasets"]
        self.assertEqual(len(datasets["beam_codebook"]["raw_response_matrix_v_rms"]), 4)
        self.assertGreater(datasets["beam_codebook"]["minimum_rejection_db"], 50.0)
        self.assertEqual(len(datasets["trim"]["gain_db_relative_to_code8_by_channel_and_code"]), 4)
        self.assertEqual(len(datasets["trim"]["gain_db_relative_to_code8_by_channel_and_code"][0]), 16)
        self.assertEqual(datasets["mismatch"]["seed_count"], 60)
        self.assertEqual(datasets["mismatch"]["passing_seed_count"], 60)
        self.assertGreaterEqual(
            datasets["mismatch"][
                "zero_failure_one_sided_95pct_pass_probability_lower_bound"
            ],
            0.95,
        )
        self.assertLess(
            datasets["sensitivity"]["compression_db"]["amplitude_50mvpk"],
            1.0,
        )
        self.assertGreater(
            datasets["twotone"]["tone_10mvpk"][
                "fundamental_to_worst_im3_db"
            ],
            40.0,
        )
        self.assertAlmostEqual(
            datasets["cold_start"]["measurements"]["vcm_near_nominal_first"] * 1e6,
            97.4555,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
