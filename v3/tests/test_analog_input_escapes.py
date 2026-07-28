from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AnalogInputEscapeFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = json.loads((ROOT / "v3/CURRENT.json").read_text(encoding="utf-8"))
        self.gate = json.loads(
            (ROOT / "v3/evidence/analog_input_escape_gate.json").read_text(encoding="utf-8")
        )
        self.frozen = ROOT / "v3/frozen/analog_input_escapes"

    def test_analog_input_checkpoint_remains_exact_frozen_upstream_input(self) -> None:
        source = json.loads(
            (ROOT / "v3/layout/digital_output_tie_plan.json").read_text(encoding="utf-8")
        )["source_checkpoint"]
        self.assertEqual(source["gds"], self.gate["gds"])
        self.assertEqual(source["sha256"], sha256(ROOT / source["gds"]))
        self.assertEqual(source["sha256"], self.gate["gds_sha256"])

    def test_topology_geometry_and_rc_are_closed(self) -> None:
        geometry = json.loads((self.frozen / "route_geometry.json").read_text(encoding="utf-8"))
        topology = json.loads(
            (self.frozen / "input_topology_audit.json").read_text(encoding="utf-8")
        )
        rc = json.loads((self.frozen / "input_rc_audit.json").read_text(encoding="utf-8"))
        precheck = json.loads(
            (self.frozen / "precheck_summary.json").read_text(encoding="utf-8")
        )

        self.assertEqual(geometry["counts"]["routes"], 4)
        self.assertEqual(geometry["counts"]["vias"], 8)
        self.assertTrue(all(route["direction_reversals"] == 0 for route in geometry["routes"]))
        self.assertEqual(topology["status"], "pass")
        self.assertEqual(topology["checks"]["distinct_input_groups"], 4)
        self.assertEqual(topology["checks"]["input_routes_shorted_to_supply"], 0)
        self.assertEqual(topology["checks"]["input_routes_shorted_to_previous_labels"], 0)
        self.assertEqual(topology["checks"]["total_extracted_devices"], 6037)
        self.assertEqual(rc["status"], "pass")
        self.assertTrue(rc["checks"]["all_four_resistance_vectors_are_identical"])
        self.assertTrue(rc["checks"]["distributed_resistors_present"])
        self.assertLess(rc["matching_metrics"]["external_capacitance_span_percent"], 2.0)
        self.assertEqual(precheck["status"], "pass")
        self.assertTrue(all(item["markers"] == 0 for item in precheck["checks"].values()))

    def test_frozen_evidence_hashes_bind_reproducible_artifacts(self) -> None:
        expected = {
            "corridor_audit": "corridor_obstructions.json",
            "route_geometry": "route_geometry.json",
            "assembly_report": "assembly_report.json",
            "direct_gds_precheck": "precheck_summary.json",
            "magic_readback_log": "magic_readback.log",
            "extraction_feedback": "extraction_feedback.txt",
            "top_ext": "v3_four_ch_analog_inputs.ext",
            "overlay_ext": "v3_analog_input_escape_routes.ext",
            "topology_audit": "input_topology_audit.json",
            "rc_audit": "input_rc_audit.json",
            "rc_magic_log": "rc_magic.log",
            "overlay_gds": "v3_analog_input_escape_routes.gds",
            "integrated_review_image": "01_integrated_input_escapes.png",
            "landing_review_image": "03_m2_input_landings.png",
            "terminal_review_image": "04_tinytapeout_analog_pads.png",
        }
        for evidence_key, filename in expected.items():
            self.assertEqual(sha256(self.frozen / filename), self.gate["sha256"][evidence_key])


if __name__ == "__main__":
    unittest.main()
