"""Regression tests for the reproducible V3 review floorplan."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


V3_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V3_ROOT / "tools"))

from build_floorplan import build_floorplan
from check_floorplan import validate_floorplan
from render_floorplan import render


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
        self.assertIn("not yet", self.data["shared_support"]["tail_reference_status"])
        self.assertIn("measure and place", self.data["shared_support"]["next_gate"])


if __name__ == "__main__":
    unittest.main()
