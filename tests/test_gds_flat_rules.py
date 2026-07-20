from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
