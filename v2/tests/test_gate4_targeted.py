import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_gate4_targeted import canonical_sha256, evaluate, extraction_binding


def result(i: float, q: float, gds_hash: str, rms: float | None = None,
           view: str = "rc", netlist_hash: str = "net"):
    return {
        "returncode": 0,
        "report": None,
        "result": {
            "status": "pass", "gds_sha256": gds_hash, "view": view,
            "netlist_sha256": netlist_hash,
            "analysis": {
                "output_tone_i_v": i, "output_tone_q_v": q,
                "output_tone_rms_v": rms if rms is not None else math.sqrt(2 * (i*i + q*q)),
            },
        },
    }


class Gate4TargetedTests(unittest.TestCase):
    def test_extraction_binding_ignores_host_paths(self) -> None:
        left = {
            "status": "pass", "sha256": {"base": "b", "distributed_rc": "r"},
            "base": {"devices": 1}, "distributed_rc": {"devices": 1, "resistors": 2},
            "required_routed_net_count": 3, "covered_routed_net_count": 3,
            "uncovered_routed_nets": [], "checks": {"coverage": True},
            "annotation": {"freshness_source_paths": ["/mac/path"]},
        }
        right = {**left, "annotation": {"freshness_source_paths": ["/server/path"]}}
        self.assertEqual(
            canonical_sha256(extraction_binding(left)),
            canonical_sha256(extraction_binding(right)),
        )

    def test_corrected_rejection_and_base_rc_delta_pass(self) -> None:
        frozen = "abc"
        cases = {
            "base_nominal_constructive": result(.01, 0, frozen, .014, "base"),
            "base_zero_input_background": result(.001, 0, frozen, view="base"),
            "rc_nominal_constructive": result(.009, 0, frozen),
            "rc_representative_null": result(.0011, 0, frozen),
            "rc_zero_input_background": result(.001, 0, frozen),
        }
        report = evaluate(cases, frozen, {"base": "net", "rc": "net"})
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertGreater(report["metrics"]["rc_representative_rejection_db"], 6)

    def test_stale_netlist_is_rejected(self) -> None:
        cases = {"only": result(.01, 0, "gds", netlist_hash="old")}
        report = evaluate(cases, "gds", {"rc": "new"})
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("stale rc netlist" in error for error in report["errors"]))

    def test_stale_hash_is_rejected(self) -> None:
        cases = {"only": result(.01, 0, "old")}
        report = evaluate(cases, "new")
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("different GDS hash" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
