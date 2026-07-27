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
from build_bias_distribution import build_manifest as build_bias_distribution
from build_input_bias_distribution import build as build_input_bias_distribution
from build_channel_matrix_placement import build as build_channel_matrix_placement
from build_shared_support_placement import build as build_shared_support_placement
from build_vector_unit_placement import build as build_vector_unit_placement
from build_selector_placement import build_selector_placement
from check_bias_distribution import validate as validate_bias_distribution
from check_floorplan import validate_floorplan
from check_input_bias_distribution import check as check_input_bias_distribution
from check_channel_matrix_placement import check as check_channel_matrix_placement
from check_shared_support_placement import check as check_shared_support_placement
from check_vector_unit_placement import check as check_vector_unit_placement
from check_selector_placement import validate as validate_selector
from render_floorplan import render
from render_selector_placement import render as render_selector
from render_shared_support_placement import render as render_shared_support_placement


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

    def test_shared_support_pilot_is_closed_but_not_integrated(self) -> None:
        support = self.data["shared_support"]
        self.assertIn("physical pilot passes", support["tail_reference_status"])
        self.assertFalse(support["tail_reference_integrated"])
        self.assertIn("three-MIM", support["next_gate"])

    def test_bias_distribution_is_reproducible_and_physically_closed(self) -> None:
        manifest_path = V3_ROOT / "layout" / "bias_distribution.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_bias_distribution())
        report = validate_bias_distribution(manifest)
        self.assertEqual(report["status"], "pass", report["errors"])
        physical = json.loads(
            (V3_ROOT / "evidence" / "tail_reference_physical_gate.json").read_text(encoding="utf-8")
        )
        self.assertEqual(physical["status"], "pass")
        self.assertTrue(all(physical["checks"].values()), physical["checks"])
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            physical["manifest_sha256"],
        )
        self.assertLessEqual(
            physical["distributed_rc"]["branch_resistance_mismatch_percent"],
            physical["distributed_rc"]["maximum_allowed_mismatch_percent"],
        )

    def test_input_bias_distribution_is_reproducible_and_balanced(self) -> None:
        path = V3_ROOT / "layout" / "input_bias_distribution.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_input_bias_distribution())
        report = check_input_bias_distribution(manifest)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["resistor_count"], 4)
        self.assertLessEqual(report["input_branch_mismatch_percent"], 0.1)
        self.assertLessEqual(report["vcm_tree_leaf_mismatch_percent"], 0.1)
        self.assertLessEqual(report["local_vcm_entry_mismatch_percent"], 0.1)
        self.assertEqual(report["physical_guard_merge_status"], "pending exact one-channel pilot")

    def test_measured_support_study_is_bound_to_its_generator(self) -> None:
        report = json.loads((V3_ROOT / "evidence" / "support_floorplan_study.json").read_text(encoding="utf-8"))
        generator = V3_ROOT.parent / report["provenance"]["generator"]
        observed = hashlib.sha256(generator.read_bytes()).hexdigest()
        self.assertEqual(observed, report["provenance"]["generator_sha256"])
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["selected_candidate"], "XREF_8X8")
        for cell in report["measured_pcells"].values():
            self.assertEqual(cell["parameters"]["aggregate_width_um"], 64.0)

    def test_shared_support_pcell_catalog_has_measured_terminal_access(self) -> None:
        report = json.loads(
            (V3_ROOT / "layout" / "shared_support_pcell_catalog.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["gates"].values()), report["gates"])
        generator = V3_ROOT.parent / report["provenance"]["generator"]
        self.assertEqual(
            hashlib.sha256(generator.read_bytes()).hexdigest(),
            report["provenance"]["generator_sha256"],
        )
        self.assertEqual(
            set(report["cells"]["XVCM_UNIT_SCALE_0P25"]["ports"]),
            {"B", "R1", "R2"},
        )
        self.assertEqual(
            set(report["cells"]["XDECAP_MIM"]["ports"]),
            {"C1", "C2"},
        )
        self.assertEqual(
            set(report["cells"]["XVCM_VAR"]["ports"]),
            {"B", "D", "G", "S"},
        )

    def test_shared_support_constraint_placement_is_reproducible(self) -> None:
        path = V3_ROOT / "layout" / "shared_support_placement.json"
        placement = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(placement, build_shared_support_placement())
        report = check_shared_support_placement(placement)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["vcm_bypass_mim_count"], 3)
        self.assertEqual(report["tail_bypass_mim_count"], 2)
        self.assertEqual(
            report["vcm_divider_centroids_um"]["A"],
            report["vcm_divider_centroids_um"]["B"],
        )
        floorplan = json.loads(
            (V3_ROOT / "layout" / "floorplan.json").read_text(encoding="utf-8")
        )
        tracked = (
            V3_ROOT / "evidence" / "shared_support_placement_review.svg"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            tracked, render_shared_support_placement(placement, floorplan)
        )

    def test_exact_vcm_support_pilot_is_current_and_physically_closed(self) -> None:
        placement_path = V3_ROOT / "layout" / "shared_support_placement.json"
        report = json.loads(
            (V3_ROOT / "evidence" / "vcm_support_physical_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(
            hashlib.sha256(placement_path.read_bytes()).hexdigest(),
            report["manifest_sha256"],
        )
        self.assertEqual(
            report["distributed_rc"]["distributed_counts"]["vcm_mim_capacitors"],
            3,
        )
        self.assertLessEqual(
            report["distributed_rc"]["maximum_effective_resistance_ohm"],
            report["distributed_rc"]["maximum_allowed_route_resistance_ohm"],
        )

    def test_exact_vector_unit_is_reproducible_and_physically_closed(self) -> None:
        manifest_path = V3_ROOT / "layout" / "vector_unit_placement.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_vector_unit_placement())
        placement = check_vector_unit_placement(manifest)
        self.assertEqual(placement["status"], "pass", placement["errors"])
        report = json.loads(
            (V3_ROOT / "evidence" / "vector_unit_physical_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            report["manifest_sha256"],
        )
        self.assertLessEqual(
            report["distributed_rc"]["gm_current_path_mismatch_percent"], 1.0
        )
        self.assertLessEqual(
            report["distributed_rc"]["output_path_mismatch_percent"], 1.0
        )
        self.assertEqual(
            report["distributed_rc"]["lo_gate_path_mismatch_percent"], 0.0
        )

    def test_channel_matrix_and_local_row_are_reproducible_and_physically_closed(self) -> None:
        manifest_path = V3_ROOT / "layout" / "channel_matrix_placement.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, build_channel_matrix_placement())
        placement = check_channel_matrix_placement(manifest)
        self.assertEqual(placement["status"], "pass", placement["errors"])
        self.assertEqual(placement["unit_count"], 15)
        for centroid in placement["group_centroids_in_unit_pitch"].values():
            self.assertEqual(centroid, [1.0, 2.0])
        report = json.loads(
            (V3_ROOT / "evidence" / "channel_row_physical_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["device_count"], 21)
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            report["sha256"]["matrix_manifest"],
        )
        generator = V3_ROOT / "tools" / "generate_channel_row_pilot.py"
        self.assertEqual(
            hashlib.sha256(generator.read_bytes()).hexdigest(),
            report["sha256"]["generator"],
        )
        full_report = json.loads(
            (V3_ROOT / "evidence" / "channel_matrix_physical_gate.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(full_report["status"], "pass")
        self.assertTrue(all(full_report["checks"].values()), full_report["checks"])
        self.assertEqual(full_report["device_count"], 105)
        self.assertEqual(
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            full_report["sha256"]["matrix_manifest"],
        )
        full_generator = V3_ROOT / "tools" / "generate_channel_matrix_pilot.py"
        self.assertEqual(
            hashlib.sha256(full_generator.read_bytes()).hexdigest(),
            full_report["sha256"]["generator"],
        )

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
        self.assertEqual(report["selected_constraints"]["signal_cell_gap_sites"], 0)
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
