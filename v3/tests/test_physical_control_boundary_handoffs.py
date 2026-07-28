from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhysicalControlBoundaryHandoffFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/physical_control_boundary_handoff_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.frozen = ROOT / "v3/frozen/controller_boundary_handoffs"

    def test_boundary_checkpoint_remains_the_exact_frozen_upstream_input(self) -> None:
        source = json.loads(
            (ROOT / "v3/layout/analog_input_escape_plan.json").read_text(encoding="utf-8")
        )["source_checkpoint"]
        self.assertEqual(source["gds"], self.gate["gds"])
        self.assertEqual(source["sha256"], sha256(ROOT / source["gds"]))
        self.assertEqual(source["sha256"], self.gate["gds_sha256"])
        self.assertEqual(source["physical_gate_sha256"], sha256(
            ROOT / "v3/evidence/physical_control_boundary_handoff_gate.json"
        ))

    def test_route_and_integrated_topology_are_closed(self) -> None:
        route = json.loads((self.frozen / "route_audit.json").read_text(encoding="utf-8"))
        topology = json.loads(
            (self.frozen / "boundary_topology_audit.json").read_text(encoding="utf-8")
        )
        precheck = json.loads(
            (self.frozen / "precheck_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(route["status"], "pass")
        self.assertEqual(route["route_count"], 14)
        self.assertEqual(route["pin_count"], 28)
        self.assertEqual(route["final_openroad_violation_count"], 0)
        self.assertEqual(route["maximum_route_layer"], "met4")

        self.assertEqual(topology["status"], "pass")
        checks = topology["checks"]
        self.assertEqual(checks["overlay_boundary_nodes"], 14)
        self.assertEqual(checks["distinct_boundary_groups"], 14)
        self.assertEqual(checks["distinct_controller_route_groups"], 305)
        self.assertEqual(checks["distinct_internal_handoff_groups"], 41)
        self.assertEqual(checks["boundary_inputs_shorted_to_supply"], 0)
        self.assertEqual(checks["boundary_inputs_shorted_to_internal_handoffs"], 0)
        self.assertEqual(checks["total_extracted_devices"], 6037)
        self.assertTrue(checks["device_population_matches_source"])
        self.assertTrue(checks["exact_tinytapeout_boundary_terminals"])
        self.assertEqual(checks["tinytapeout_boundary_terminal_count"], 14)

        self.assertEqual(precheck["status"], "pass")
        self.assertTrue(all(item["markers"] == 0 for item in precheck["checks"].values()))

    def test_frozen_evidence_hashes_bind_the_reproducible_artifacts(self) -> None:
        expected = {
            "input_def": "input.def",
            "input_summary": "input_summary.json",
            "routed_def": "routed.def",
            "route_audit": "route_audit.json",
            "detailed_route_drc": "detailed_route_drc.rpt",
            "openroad_log": "openroad.log",
            "wire_length": "wire_length.csv",
            "guide_coverage": "guide_coverage.csv",
            "route_guide": "route.guide",
            "route_geometry": "route_geometry.json",
            "assembly_report": "assembly_report.json",
            "direct_gds_precheck": "precheck_summary.json",
            "magic_readback_log": "magic_readback.log",
            "extraction_feedback": "extraction_feedback.txt",
            "top_ext": "v3_four_ch_ctrl_boundary_handoff.ext",
            "overlay_ext": "v3_ctrl_boundary_handoff_routes.ext",
            "topology_audit": "boundary_topology_audit.json",
            "overlay_gds": "v3_control_boundary_handoff_routes.gds",
            "integrated_review_image": "01_integrated_boundary_handoffs.png",
            "terminal_review_image": "03_tinytapeout_pin_landings.png",
        }
        for evidence_key, filename in expected.items():
            self.assertEqual(
                sha256(self.frozen / filename),
                self.gate["sha256"][evidence_key],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
