import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_gate5_mismatch_pilot import (
    MODEL_SPECS,
    build_model_bundle,
    frozen_report_identity_errors,
    patch_pm3,
    transform_netlist,
    zero_failure_lower_bound,
)
from run_control_postlayout_smoke import SPICE_INIT


class Gate5MismatchPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = ROOT / "build/v2/control_routing/final_rc/control_final_base.spice"

    def test_pdk_model_patch_exposes_local_mismatch_factors(self) -> None:
        model = "sky130_fd_pr__nfet_01v8"
        spec = MODEL_SPECS[model]
        text = (ROOT / spec["pm3"]).read_text()
        patched = patch_pm3(text, model, spec["parameters"])
        self.assertIn("mc_nfet_01v8_vth0=0", patched)
        self.assertIn(
            "(sky130_fd_pr__nfet_01v8__vth0_slope_spectre+mc_nfet_01v8_vth0)",
            patched,
        )
        self.assertIn(".param sky130_fd_pr__nfet_01v8__vth0_slope_spectre = 0.0", patched)

    def test_transform_is_seeded_complete_and_reproducible(self) -> None:
        text = self.base.read_text(errors="replace")
        first, manifest = transform_netlist(text, 7)
        second, second_manifest = transform_netlist(text, 7)
        other, _ = transform_netlist(text, 8)
        self.assertEqual(first, second)
        self.assertEqual(manifest, second_manifest)
        self.assertNotEqual(first, other)
        self.assertNotIn("sky130_fd_pr__special_nfet_01v8", first)
        self.assertEqual(
            manifest["device_counts"],
            {"sky130_fd_pr__nfet_01v8": 2336, "sky130_fd_pr__pfet_01v8_hvt": 1858},
        )
        self.assertIn("mc_nfet_01v8_vth0=", first)
        self.assertIn("mc_pfet_01v8_hvt_vth0=", first)

    def test_bundle_is_hash_bound_and_documents_limitations(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as first_directory:
            with tempfile.TemporaryDirectory(dir=ROOT / "build") as second_directory:
                _first_include, first = build_model_bundle(Path(first_directory))
                _second_include, second = build_model_bundle(Path(second_directory))
                self.assertIn("not foundry-qualified Monte Carlo", first["limitations"])
                self.assertEqual(set(first["files"]), set(MODEL_SPECS))
                self.assertEqual(len(first["bundle_sha256"]), 64)
                self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
                self.assertNotEqual(first["include_sha256"], second["include_sha256"])

    def test_zero_failure_campaign_bound_is_explicit(self) -> None:
        self.assertAlmostEqual(zero_failure_lower_bound(60), 0.9512970866899025)
        self.assertLess(zero_failure_lower_bound(8), 0.7)
        with self.assertRaises(ValueError):
            zero_failure_lower_bound(0)

    def test_frozen_report_merge_rejects_cross_artifact_or_timed_out_cases(self) -> None:
        expected = {
            "view": "base",
            "selected_beam": 0,
            "incident_beam": 1,
            "input_peak_v": 0.005,
            "gds_sha256": "g" * 64,
            "netlist_sha256": "n" * 64,
            "model_bundle_sha256": "m" * 64,
            "spiceinit_sha256": hashlib.sha256(SPICE_INIT.encode()).hexdigest(),
            "ngspice_returncode": 0,
            "timed_out": False,
        }
        arguments = {
            "view": "base", "incident": 1, "amplitude": 0.005,
            "gds_hash": "g" * 64, "netlist_hash": "n" * 64,
            "model_bundle_hash": "m" * 64,
        }
        self.assertEqual(frozen_report_identity_errors(expected, **arguments), [])
        expected["timed_out"] = True
        expected["netlist_sha256"] = "x" * 64
        self.assertEqual(
            set(frozen_report_identity_errors(expected, **arguments)),
            {"timed_out differs", "netlist_sha256 differs"},
        )


if __name__ == "__main__":
    unittest.main()
