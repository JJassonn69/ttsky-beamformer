from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from tools.check_gds_flat_rules import CAPM, MET3, MET4, audit_rectangles


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
            MET3: [
                (0.0, 0.0, 1.0, 1.0),
                (1.2, 0.0, 2.2, 1.0),
                (6.5, 0.0, 7.5, 1.0),
            ],
            MET4: [
                (0.0, 3.0, 0.2, 4.0),
                (2.0, 3.0, 2.4, 3.4),
                (2.6, 3.0, 3.0, 3.4),
            ],
            CAPM: [(5.0, 0.0, 6.0, 1.0)],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertTrue(all(checks.values()), checks)

    def test_rule_clean_synthetic_geometry_has_no_markers(self) -> None:
        rectangles = {
            MET3: [(0.0, 0.0, 1.0, 1.0), (2.0, 0.0, 3.0, 1.0)],
            MET4: [(0.0, 3.0, 0.5, 3.5), (2.0, 3.0, 2.5, 3.5)],
            CAPM: [(5.0, 0.0, 6.0, 1.0)],
        }
        _components, checks = audit_rectangles(rectangles)
        self.assertFalse(any(checks.values()), checks)


if __name__ == "__main__":
    unittest.main()
