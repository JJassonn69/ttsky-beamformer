"""Regression tests for the reproducible V3 review floorplan."""

from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path


V3_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V3_ROOT / "tools"))

from build_floorplan import build_floorplan
from build_selector_placement import build_selector_placement
from check_floorplan import validate_floorplan
from check_selector_placement import validate as validate_selector
from render_floorplan import render
from render_selector_placement import render as render_selector


class V3FloorplanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_path = V3_ROOT / "layout" / "floorplan.json"
        self.data = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def test_manifest_is_reproducible(self) -> None:
        self.assertEqual(self.data, build_floorplan())

    def test_floorplan_contract(self) -> None:
        report = validate_floorplan(self.data)
        self.assertEqual(report["status"], "pass", report["errors"])

    def test_review_svg_is_reproducible(self) -> None:
        tracked = (V3_ROOT / "evidence" / "floorplan_review.svg").read_text(encoding="utf-8")
        self.assertEqual(tracked, render(self.data))

    def test_floorplan_does_not_authorize_geometry(self) -> None:
        auth = self.data["authorization"]
        self.assertTrue(auth["floorplan_authorized"])
        self.assertFalse(auth["device_placement_authorized"])
        self.assertFalse(auth["routing_authorized"])
        self.assertFalse(auth["gds_authorized"])

    def test_all_route_classes_ban_reversals(self) -> None:
        for name, constraints in self.data["net_classes"].items():
            self.assertEqual(constraints["max_direction_reversals"], 0, name)

    def test_shared_support_is_explicitly_unplaced(self) -> None:
        self.assertIn("DRC/LVS pending", self.data["shared_support"]["tail_reference_status"])
        self.assertIn("draw/extract", self.data["shared_support"]["next_gate"])

    def test_measured_support_study_is_bound_to_its_generator(self) -> None:
        report = json.loads((V3_ROOT / "evidence" / "support_floorplan_study.json").read_text(encoding="utf-8"))
        generator = V3_ROOT.parent / report["provenance"]["generator"]
        observed = hashlib.sha256(generator.read_bytes()).hexdigest()
        self.assertEqual(observed, report["provenance"]["generator_sha256"])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["selected_candidate"], "XREF_8X8")
        for cell in report["measured_pcells"].values():
            self.assertEqual(cell["parameters"]["aggregate_width_um"], 64.0)

    def test_selector_placement_is_reproducible_and_valid(self) -> None:
        path = V3_ROOT / "layout" / "selector_placement.json"
        placement = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(placement, build_selector_placement())
        report = validate_selector(placement)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertLess(report["raw_cell_utilization_percent"], 45.0)
        tracked_svg = (V3_ROOT / "evidence" / "selector_placement_review.svg").read_text(encoding="utf-8")
        self.assertEqual(tracked_svg, render_selector(placement))

    def test_selector_route_pilot_evidence_is_current_and_precheck_clean(self) -> None:
        report = json.loads((V3_ROOT / "evidence" / "selector_route_pilot.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(
            set(report["tiny_tapeout_precheck_compatible_geometry"]["marker_counts"].values()),
            {0},
        )
        self.assertEqual(report["selected_constraints"]["row_gap_um"], 0.0)
        self.assertEqual(report["selected_constraints"]["signal_cell_gap_sites"], 1)
        placement_path = V3_ROOT / "layout" / "selector_placement.json"
        route_generator = V3_ROOT / "tools" / "generate_selector_route_pilot.py"
        precheck_runner = V3_ROOT / "tools" / "run_selector_precheck.py"
        self.assertEqual(
            hashlib.sha256(placement_path.read_bytes()).hexdigest(),
            report["provenance"]["selector_placement_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(route_generator.read_bytes()).hexdigest(),
            report["provenance"]["route_generator_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(precheck_runner.read_bytes()).hexdigest(),
            report["provenance"]["precheck_runner_sha256"],
        )
        self.assertIn("full wrapper/pin/boundary/interface checks require", report["tiny_tapeout_precheck_compatible_geometry"]["scope_note"])


if __name__ == "__main__":
    unittest.main()
