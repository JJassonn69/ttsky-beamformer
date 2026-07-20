from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.check_generated_routes import (
    dead_end_via3_errors,
    disconnected_route_errors,
    endpoint_matching_results,
    expand_endpoint_constraints,
    matching_results,
    parse_route,
    path_matching_results,
    route_metrics,
    same_layer_spacing_errors,
    top_boundary_clearance_errors,
    via_connection_errors,
)


class RouteConstraintTests(unittest.TestCase):
    def test_endpoint_pair_group_expands_to_independent_constraints(self) -> None:
        constraints = [{
            "name": "branches",
            "endpoint_pairs": [["a.G", "b.G"], ["c.G", "d.G"]],
            "nets": ["left", "right"],
        }]
        expanded = expand_endpoint_constraints(constraints)
        self.assertEqual([item["name"] for item in expanded], [
            "branches_01", "branches_02",
        ])
        self.assertEqual(expanded[1]["endpoints"], ["c.G", "d.G"])

    def test_metrics_union_repeated_wire_and_ignore_via_landing(self) -> None:
        route = """# horizontal net track: a
paint_rect metal3 0.0 0.0 10.0 0.4
paint_rect metal3 5.0 0.0 12.0 0.4
paint_rect metal3 20.0 0.0 20.0 5.0
paint_rect metal3 9.69 0.0 10.31 0.4
paint_rect via3 9.8 0.0 10.2 0.4
paint_rect metal4 9.8 0.0 10.2 0.4
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            metrics = route_metrics(parse_route(path))
        self.assertAlmostEqual(metrics["a"]["wire_length_um"]["metal3"], 12.0)
        self.assertEqual(metrics["a"]["via_sites"]["via3"], 1)

    def test_pair_constraint_detects_length_and_via_mismatch(self) -> None:
        metrics = {
            "a": {
                "wire_length_um": {"metal1": 0, "metal2": 0, "metal3": 10, "metal4": 20},
                "via_sites": {"via1": 1, "via2": 1, "via3": 2},
            },
            "b": {
                "wire_length_um": {"metal1": 0, "metal2": 0, "metal3": 10, "metal4": 18},
                "via_sites": {"via1": 1, "via2": 1, "via3": 1},
            },
        }
        constraints = [{
            "name": "pair",
            "nets": ["a", "b"],
            "layers": ["metal3", "metal4"],
            "max_layer_length_mismatch_percent": 2,
            "max_total_length_mismatch_percent": 2,
            "equal_vias": ["via1", "via2", "via3"],
        }]
        results, failures = matching_results(metrics, constraints)
        self.assertFalse(results[0]["passed"])
        self.assertTrue(any("metal4 length mismatch" in failure for failure in failures))
        self.assertTrue(any("via3 site count" in failure for failure in failures))

    def test_endpoint_constraint_includes_track_and_boundary_route(self) -> None:
        route = """# horizontal net track: a
paint_rect metal3 0 0 10 0.4
# dev.G -> a
paint_rect metal4 0 0 0.4 5
# TinyTapeout boundary pin -> a
paint_rect metal4 9.6 -5 10 0
# horizontal net track: b
paint_rect metal3 0 1 10 1.4
# peer.G -> b
paint_rect metal4 0 1 0.4 6
# TinyTapeout boundary pin -> b
paint_rect metal4 9.6 -4 10 1
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            shapes = parse_route(path)
        constraints = [{
            "name": "endpoints",
            "endpoints": ["dev.G", "peer.G"],
            "nets": ["a", "b"],
            "layers": ["metal3", "metal4"],
            "max_layer_length_mismatch_percent": 0,
            "max_total_length_mismatch_percent": 0,
            "equal_vias": [],
        }]
        results, failures = endpoint_matching_results(shapes, constraints)
        self.assertTrue(results[0]["passed"], failures)

    def test_functional_path_uses_both_endpoint_branches(self) -> None:
        route = """# horizontal net track: a
paint_rect metal3 0 0 1 0.4
# src.D -> a
paint_rect metal4 0 0 0.4 5
# load.G -> a
paint_rect metal4 0.6 0 1 5
# horizontal net track: b
paint_rect metal3 0 1 1 1.4
# peer_src.D -> b
paint_rect metal4 0 1 0.4 6
# peer_load.G -> b
paint_rect metal4 0.6 1 1 6
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            shapes = parse_route(path)
        constraints = [{
            "name": "paths",
            "path_pairs": [
                [["src.D", "load.G"], ["peer_src.D", "peer_load.G"]],
            ],
            "nets": ["a", "b"],
            "layers": ["metal3", "metal4"],
            "max_layer_length_mismatch_percent": 0,
            "max_total_length_mismatch_percent": 0,
            "equal_vias": [],
        }]
        results, failures = path_matching_results(shapes, constraints)
        self.assertTrue(results[0]["passed"], failures)

    def test_top_boundary_clearance_rejects_unused_pin_near_m4(self) -> None:
        route = """# device.D -> internal
paint_rect metal4 124.33 219.67 124.73 224.57
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = top_boundary_clearance_errors(parse_route(path))
        self.assertEqual(len(failures), 1)
        self.assertIn("ui_in[5]", failures[0])
        self.assertIn("0.190 um", failures[0])

    def test_top_boundary_clearance_allows_intended_clock_connection(self) -> None:
        route = """# TinyTapeout boundary pin -> clk
paint_rect metal4 143.80 128.70 144.20 225.26
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = top_boundary_clearance_errors(parse_route(path))
        self.assertEqual(failures, [])

    def test_cross_net_via_to_adjacent_metal_overlap_is_rejected(self) -> None:
        route = """# first.D -> first
paint_rect via3 10.0 10.0 10.4 10.4
# second.G -> second
paint_rect metal3 9.9 10.0 10.5 10.4
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = via_connection_errors(parse_route(path))
        self.assertEqual(len(failures), 1)
        self.assertIn("via3", failures[0])
        self.assertIn("metal3", failures[0])

    def test_cross_net_m3_spacing_is_rejected_before_gds(self) -> None:
        route = """# first.D -> first
paint_rect metal3 0.0 0.0 4.0 0.4
# second.G -> second
paint_rect metal3 0.0 0.53 4.0 0.93
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = same_layer_spacing_errors(parse_route(path))
        self.assertEqual(len(failures), 1)
        self.assertIn("0.130 um", failures[0])
        self.assertIn("minimum is 0.30 um", failures[0])

    def test_disconnected_same_net_route_is_rejected(self) -> None:
        route = """# device.D -> signal
paint_rect metal3 0.0 0.0 1.0 0.4
paint_rect metal3 5.0 0.0 6.0 0.4
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = disconnected_route_errors(parse_route(path))
        self.assertEqual(len(failures), 1)
        self.assertIn("signal", failures[0])
        self.assertIn("disconnected", failures[0])

    def test_dead_end_via3_requires_real_continuation_on_both_sides(self) -> None:
        dead_end = """# device.D -> signal
paint_rect metal3 9.69 10.0 10.31 10.4
paint_rect via3 9.8 10.0 10.2 10.4
paint_rect metal4 9.8 10.0 10.2 10.4
"""
        continued = dead_end + """paint_rect via2 9.8 10.0 10.2 10.4
paint_rect metal4 9.8 10.0 10.2 12.0
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(dead_end)
            failures = dead_end_via3_errors(parse_route(path))
            self.assertEqual(len(failures), 2)
            self.assertTrue(any("M3" in failure for failure in failures))
            self.assertTrue(any("M4" in failure for failure in failures))
            path.write_text(continued)
            self.assertEqual(dead_end_via3_errors(parse_route(path)), [])

    def test_wide_stale_m3_track_below_one_m4_component_is_rejected(self) -> None:
        route = """# horizontal net track: signal
paint_rect metal3 9.6 10.0 10.4 10.4
paint_rect via3 9.8 10.0 10.2 10.4
paint_rect metal4 9.8 5.0 10.2 12.0
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.tcl"
            path.write_text(route)
            failures = dead_end_via3_errors(parse_route(path))
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("via-only M3 island", failures[0])


if __name__ == "__main__":
    unittest.main()
