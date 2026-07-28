from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhysicalControlAnalogHandoffFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/physical_control_analog_handoff_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.frozen = ROOT / "v3/frozen/controller_analog_handoffs"

    def test_analog_handoff_checkpoint_remains_the_exact_frozen_upstream_input(self) -> None:
        self.assertEqual(
            self.current["four_channel_integration"]["centralized_control_to_analog_handoffs"],
            "v3/evidence/physical_control_analog_handoff_gate.json",
        )
        self.assertEqual(
            self.gate["gds_sha256"],
            sha256(self.frozen / "v3_four_channel_ctrl_analog_handoffs.gds"),
        )
        self.assertEqual(
            self.gate["flat_spice_sha256"],
            sha256(self.frozen / "v3_four_ch_ctrl_analog_handoff_flat.spice"),
        )

    def test_route_and_integrated_topology_are_closed(self) -> None:
        route = json.loads((self.frozen / "route_audit.json").read_text(encoding="utf-8"))
        topology = json.loads(
            (self.frozen / "handoff_topology_audit.json").read_text(encoding="utf-8")
        )
        precheck = json.loads(
            (self.frozen / "precheck_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(route["status"], "pass")
        self.assertEqual(route["route_count"], 41)
        self.assertEqual(route["pin_count"], 85)
        self.assertEqual(route["final_openroad_violation_count"], 0)
        self.assertEqual(route["maximum_route_layer"], "met4")

        self.assertEqual(topology["status"], "pass")
        checks = topology["checks"]
        self.assertEqual(checks["overlay_handoff_nodes"], 41)
        self.assertEqual(checks["distinct_handoff_groups"], 41)
        self.assertEqual(checks["distinct_controller_route_groups"], 305)
        self.assertEqual(checks["handoffs_shorted_to_supply"], 0)
        self.assertEqual(checks["controller_routes_shorted_to_supply"], 0)
        self.assertEqual(checks["total_extracted_devices"], 6037)
        self.assertTrue(checks["device_population_matches_powered_source"])
        self.assertEqual(set(checks["phase_selector_terminal_hits"].values()), {32})
        self.assertTrue(
            all(channels == [0, 1, 2, 3] for channels in checks["phase_selector_channels"].values())
        )

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
            "top_ext": "v3_four_ch_ctrl_analog_handoff.ext",
            "overlay_ext": "v3_ctrl_analog_handoff_routes.ext",
            "topology_audit": "handoff_topology_audit.json",
            "overlay_gds": "v3_control_analog_handoff_routes.gds",
        }
        for evidence_key, filename in expected.items():
            self.assertEqual(
                sha256(self.frozen / filename),
                self.gate["sha256"][evidence_key],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
