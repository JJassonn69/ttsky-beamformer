import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_gate5_clock_pilot import cases


class Gate5ClockPilotTests(unittest.TestCase):
    def test_matrix_is_bounded_and_separates_duty_from_jitter(self) -> None:
        matrix = cases(123)
        self.assertEqual(
            set(matrix),
            {"duty_40pct", "duty_60pct", "jitter_500ps", "jitter_1000ps"},
        )
        self.assertTrue(all("--timeout" in command for command in matrix.values()))
        self.assertIn("--clock-duty-percent", matrix["duty_40pct"])
        self.assertNotIn("--clock-jitter-ps", matrix["duty_40pct"])
        self.assertIn("--clock-jitter-ps", matrix["jitter_1000ps"])


if __name__ == "__main__":
    unittest.main()
