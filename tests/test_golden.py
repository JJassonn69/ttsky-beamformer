import cmath
import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "model"))

from beamformer import AnalogPath, Channel, beam_phasor, null_depth_db, rc_transfer


class GoldenBeamformerTests(unittest.TestCase):
    def test_equal_channels_combine_constructively(self) -> None:
        result = beam_phasor(Channel(), Channel())
        self.assertAlmostEqual(abs(result), 0.005, places=12)
        self.assertAlmostEqual(cmath.phase(result), 0.0, places=12)

    def test_lo_polarity_cancels_equal_channels(self) -> None:
        result = beam_phasor(Channel(), Channel(lo_phase_deg=180.0))
        self.assertLess(abs(result), 1.0e-15)

    def test_quadrature_lo_aligns_quadrature_input(self) -> None:
        result = beam_phasor(
            Channel(),
            Channel(input_phase_deg=90.0, lo_phase_deg=90.0),
        )
        self.assertAlmostEqual(abs(result), 0.005, places=12)
        self.assertAlmostEqual(cmath.phase(result), 0.0, places=12)

    def test_maximum_tt_path_at_5mhz_matches_rc_calculation(self) -> None:
        transfer = rc_transfer(5.0e6, AnalogPath(500.0, 5.0e-12))
        self.assertAlmostEqual(20.0 * math.log10(abs(transfer)), -0.0267, places=3)
        self.assertAlmostEqual(math.degrees(cmath.phase(transfer)), -4.491, places=3)

    def test_core_error_budget_supports_better_than_25db_null(self) -> None:
        self.assertGreater(null_depth_db(0.5, 3.0), 25.0)

    def test_system_error_budget_supports_20db_null(self) -> None:
        depth = null_depth_db(1.0, 8.0)
        self.assertGreater(depth, 20.0)
        self.assertLess(depth, 22.0)


if __name__ == "__main__":
    unittest.main()
