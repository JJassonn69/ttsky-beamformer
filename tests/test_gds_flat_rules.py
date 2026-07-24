from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from tools.check_gds_flat_rules import (
    CAPM,
    MET2,
    MET3,
    MET4,
    VIA2,
    VIA3,
    audit_rectangles,
    orthogonal_polygon_rectangles,
    minimum_width_violations,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseGdsRegressionTest(unittest.TestCase):
    def test_flattened_release_gds_has_no_known_interaction_markers(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "check_gds_flat_rules.py"),
                str(ROOT / "gds" / "tt_um_jjassonn69_beamformer.gds"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class GdsRuleUnitTests(unittest.TestCase):
    def test_orthogonal_polygon_is_decomposed_without_area_loss(self) -> None:
        points = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2), (0, 0)]
        rectangles = orthogonal_polygon_rectangles(points, 1.0)
        self.assertEqual(rectangles, [(0.0, 0.0, 2.0, 1.0), (0.0, 1.0, 1.0, 2.0)])
        self.assertEqual(sum((x1-x0)*(y1-y0) for x0, y0, x1, y1 in rectangles), 3.0)

    def test_all_escaped_rule_classes_are_detected(self) -> None:
        rectangles = {
            MET2: [],
            VIA2: [],
            MET3: [
                (0.0, 0.0, 1.0, 1.0),
                (1.2, 0.0, 2.2, 1.0),
                (6.5, 0.0, 7.5, 1.0),
                (8.0, 0.0, 8.4, 0.4),
            ],
            MET4: [
                (0.0, 3.0, 0.2, 4.0),
                (2.0, 3.0, 2.4, 3.4),
                (2.6, 3.0, 3.0, 3.4),
                (8.0, -1.0, 8.4, 1.0),
            ],
            VIA3: [
                (4.0, 3.0, 4.2, 3.2),
                (8.1, 0.1, 8.3, 0.3),
            ],
            CAPM: [(5.0, 0.0, 6.0, 1.0)],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertTrue(all(checks.values()), checks)

    def test_rule_clean_synthetic_geometry_has_no_markers(self) -> None:
        rectangles = {
            MET2: [(0.0, -1.0, 1.0, 0.2)],
            VIA2: [(0.1, 0.0, 0.3, 0.2)],
            MET3: [(0.0, 0.0, 1.0, 1.0), (2.0, 0.0, 3.0, 1.0)],
            MET4: [
                (0.0, 0.0, 0.5, 0.5),
                (0.0, 3.0, 0.5, 3.5),
                (2.0, 3.0, 2.5, 3.5),
            ],
            VIA3: [(0.1, 0.1, 0.3, 0.3)],
            CAPM: [(5.0, 0.0, 6.0, 1.0)],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertFalse(any(checks.values()), checks)

    def test_via3_accepts_union_enclosure_at_rectangle_junction(self) -> None:
        rectangles = {
            MET2: [(0.0, -1.0, 1.0, 0.2)],
            VIA2: [(0.1, 0.0, 0.3, 0.2)],
            MET3: [(0.0, 0.0, 1.0, 0.15), (0.0, 0.15, 1.0, 1.0)],
            MET4: [(0.0, 0.0, 1.0, 1.0)],
            VIA3: [(0.4, 0.1, 0.6, 0.3)],
            CAPM: [],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertFalse(checks["via3 enclosure"], checks)

    def test_via3_landing_without_m3_continuation_is_rejected(self) -> None:
        rectangles = {
            MET2: [],
            VIA2: [],
            MET3: [(0.0, 0.0, 0.4, 0.4)],
            MET4: [(0.0, -1.0, 0.4, 1.0)],
            VIA3: [(0.1, 0.1, 0.3, 0.3)],
            CAPM: [],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertTrue(checks["via-only met3 island"], checks)

    def test_magic_wire_fractures_are_checked_as_a_union(self) -> None:
        # Three abutting serialization pieces form one legal 0.50 um wire.
        fragments = [
            (0.0, 0.00, 5.0, 0.05),
            (0.0, 0.05, 5.0, 0.45),
            (0.0, 0.45, 5.0, 0.50),
        ]
        self.assertEqual(minimum_width_violations(fragments, 0.30), [])

    def test_staggered_magic_wire_fractures_are_checked_locally(self) -> None:
        # The supporting rectangles step at x=4 but remain 0.40 um wide on
        # both sides.  This is one legal conductor, not a 0.20 um stub.
        fragments = [
            (0.0, 0.0, 4.0, 0.2),
            (0.0, 0.2, 5.0, 0.4),
            (4.0, 0.4, 5.0, 0.6),
        ]
        self.assertEqual(minimum_width_violations(fragments, 0.30), [])

    def test_real_narrow_attached_stub_remains_a_width_violation(self) -> None:
        geometry = [
            (0.0, 0.0, 1.0, 1.0),
            (1.0, 0.4, 3.0, 0.6),
        ]
        violations = minimum_width_violations(geometry, 0.30)
        self.assertEqual(len(violations), 1)
        self.assertAlmostEqual(violations[0], 0.2)


if __name__ == "__main__":
    unittest.main()
