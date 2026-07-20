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


if __name__ == "__main__":
    unittest.main()
