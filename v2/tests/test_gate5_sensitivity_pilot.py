import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_gate5_sensitivity_pilot import cases


class Gate5SensitivityPilotTests(unittest.TestCase):
    def test_matrix_is_bounded_and_keeps_the_rated_lo(self) -> None:
        matrix = cases(123)
        self.assertEqual(len(matrix), 8)
        self.assertEqual(set(name for name in matrix if name.startswith("rf_")), {"rf_4p5mhz", "rf_6mhz"})
        for command in matrix.values():
            self.assertIn("base", command)
            self.assertIn("--incident-beam", command)
            self.assertNotIn("--process-corner", command)
            self.assertNotIn("--lo-frequency-mhz", command)


if __name__ == "__main__":
    unittest.main()
