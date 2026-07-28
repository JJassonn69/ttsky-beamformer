from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhysicalControlPowerFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/physical_control_power_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.frozen = ROOT / "v3/frozen/controller_power"

    def test_power_checkpoint_remains_the_exact_frozen_upstream_input(self) -> None:
        self.assertEqual(
            self.current["four_channel_integration"]["centralized_control_power"],
            "v3/evidence/physical_control_power_gate.json",
        )
        self.assertEqual(
            self.gate["gds_sha256"],
            sha256(self.frozen / "v3_four_channel_ctrl_powered.gds"),
        )
        self.assertEqual(
            self.gate["flat_spice_sha256"],
            sha256(self.frozen / "v3_four_channel_ctrl_powered_flat.spice"),
        )

    def test_power_and_integrated_topology_are_closed(self) -> None:
        topology = json.loads(
            (self.frozen / "power_topology_audit.json").read_text(encoding="utf-8")
        )
        precheck = json.loads(
            (self.frozen / "precheck_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(topology["status"], "pass")
        checks = topology["checks"]
        self.assertEqual(checks["power_overlay_nodes"], ["VDPWR", "VGND"])
        self.assertEqual(checks["power_overlay_component_counts"], {"VDPWR": 1, "VGND": 1})
        self.assertEqual(checks["power_overlay_orphan_vias"], 0)
        self.assertEqual(checks["route_labels_in_flat_extraction"], 305)
        self.assertEqual(checks["routes_shorted_to_supply"], 0)
        self.assertEqual(checks["total_extracted_devices"], 6037)
        self.assertTrue(checks["vdpwr_and_vgnd_are_distinct"])
        self.assertEqual(precheck["status"], "pass")
        self.assertTrue(all(item["markers"] == 0 for item in precheck["checks"].values()))

    def test_frozen_evidence_hashes_bind_the_reproducible_artifacts(self) -> None:
        expected = {
            "assembly_report": "assembly_report.json",
            "power_geometry": "power_geometry.json",
            "power_topology_audit": "power_topology_audit.json",
            "direct_gds_precheck": "precheck_summary.json",
            "magic_readback_log": "magic_readback.log",
            "extraction_feedback": "extraction_feedback.txt",
            "top_ext": "v3_four_channel_ctrl_powered.ext",
            "overlay_ext": "v3_ctrl_power_routes.ext",
        }
        for evidence_key, filename in expected.items():
            self.assertEqual(
                sha256(self.frozen / filename),
                self.gate["sha256"][evidence_key],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
