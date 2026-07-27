from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhysicalControlSignalRoutingFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/physical_control_signal_routing_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.frozen = ROOT / "v3/frozen/controller_signal_routing"

    def test_current_top_is_the_exact_frozen_signal_route(self) -> None:
        top = self.current["current_top_level"]
        self.assertEqual(top["physical_gate"], "v3/evidence/physical_control_signal_routing_gate.json")
        self.assertEqual(top["gds_sha256"], sha256(ROOT / top["gds"]))
        self.assertEqual(top["flat_spice_sha256"], sha256(ROOT / top["flat_spice"]))
        self.assertEqual(self.gate["gds_sha256"], top["gds_sha256"])
        self.assertEqual(self.gate["flat_spice_sha256"], top["flat_spice_sha256"])

    def test_independent_route_and_extraction_audits_are_frozen(self) -> None:
        route = json.loads((self.frozen / "route_audit.json").read_text(encoding="utf-8"))
        topology = json.loads(
            (self.frozen / "gds_topology_audit.json").read_text(encoding="utf-8")
        )
        precheck = json.loads(
            (self.frozen / "precheck_summary.json").read_text(encoding="utf-8")
        )

        self.assertEqual(route["status"], "pass")
        self.assertEqual(route["expected_route_count"], 305)
        self.assertEqual(route["final_openroad_violation_count"], 0)
        self.assertEqual(route["inaccessible_standard_cell_pin_count"], 0)
        self.assertEqual(route["maximum_route_layer"], "met3")

        self.assertEqual(topology["status"], "pass")
        checks = topology["checks"]
        self.assertEqual(checks["route_labels_expected"], 305)
        self.assertEqual(checks["route_labels_in_flat_extraction"], 305)
        self.assertEqual(checks["route_merge_groups"], 305)
        self.assertEqual(checks["route_labels_with_device_incidence"], 305)
        self.assertEqual(checks["extracted_devices"], 6037)
        self.assertTrue(checks["extraction_warning_baseline_exact"])

        self.assertEqual(precheck["status"], "pass")
        self.assertTrue(all(item["markers"] == 0 for item in precheck["checks"].values()))

    def test_frozen_evidence_hashes_bind_the_reproducible_artifacts(self) -> None:
        expected = {
            "input_summary": "input_summary.json",
            "route_audit": "route_audit.json",
            "gds_topology_audit": "gds_topology_audit.json",
            "direct_gds_precheck": "precheck_summary.json",
            "routed_def": "routed.def",
            "openroad_log": "openroad.log",
            "detailed_route_drc": "detailed_route_drc.rpt",
            "magic_readback_log": "magic_readback.log",
            "extraction_feedback": "extraction_feedback.txt",
        }
        for evidence_key, filename in expected.items():
            self.assertEqual(
                sha256(self.frozen / filename),
                self.gate["sha256"][evidence_key],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
