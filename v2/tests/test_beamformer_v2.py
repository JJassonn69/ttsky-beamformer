import cmath
import math
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "model"))

from beamformer_v2 import (
    Channel,
    codebook_response_matrix,
    rx_combined,
    rx_phase_codes,
    trim_scale,
    tx_outputs,
    tx_phase_codes,
)


class FourChannelBeamformerTests(unittest.TestCase):
    def test_tx_codebook_matches_four_point_dft(self) -> None:
        self.assertEqual(tx_phase_codes(0), (0, 0, 0, 0))
        self.assertEqual(tx_phase_codes(1), (0, 1, 2, 3))
        self.assertEqual(tx_phase_codes(2), (0, 2, 0, 2))
        self.assertEqual(tx_phase_codes(3), (0, 3, 2, 1))

    def test_receive_codes_are_transmit_conjugates(self) -> None:
        self.assertEqual(rx_phase_codes(0), (0, 0, 0, 0))
        self.assertEqual(rx_phase_codes(1), (0, 3, 2, 1))
        self.assertEqual(rx_phase_codes(2), (0, 2, 0, 2))
        self.assertEqual(rx_phase_codes(3), (0, 1, 2, 3))

    def test_ideal_codebook_is_orthogonal(self) -> None:
        matrix = codebook_response_matrix()
        for selected_beam, row in enumerate(matrix):
            for incident_beam, value in enumerate(row):
                if selected_beam == incident_beam:
                    self.assertAlmostEqual(abs(value), 4.0, places=12)
                else:
                    self.assertLess(abs(value), 1.0e-12)

    def test_tx_outputs_have_equal_amplitude(self) -> None:
        for beam_index in range(4):
            outputs = tx_outputs(0.01 + 0.0j, beam_index)
            for output in outputs:
                self.assertAlmostEqual(abs(output), 0.01, places=12)

    def test_manual_receive_phase_codes_can_align_quadrature_inputs(self) -> None:
        channels = tuple(
            Channel(input_phase_deg=phase)
            for phase in (0.0, 90.0, 180.0, 270.0)
        )
        result = rx_combined(
            channels,
            beam_index=0,
            manual_phase_codes=(0, 3, 2, 1),
        )
        self.assertAlmostEqual(abs(result), 0.02, places=12)
        self.assertAlmostEqual(cmath.phase(result), 0.0, places=12)

    def test_trim_matches_equal_unit_switched_tail_bank(self) -> None:
        self.assertAlmostEqual(trim_scale(0), 32.0 / 40.0, places=12)
        self.assertAlmostEqual(trim_scale(8), 1.0, places=12)
        self.assertAlmostEqual(trim_scale(15), 47.0 / 40.0, places=12)

    def test_invalid_trim_code_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            trim_scale(16)


if __name__ == "__main__":
    unittest.main()
