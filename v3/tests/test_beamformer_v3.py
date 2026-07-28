import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/model"))

from beamformer_v3 import (
    AXIS_VECTORS,
    CHANNEL_COUNT,
    GROUP_WEIGHTS,
    TOTAL_UNIT_SLICES,
    accounted_unit_slices,
    array_response,
    beam_response_matrix,
    constellation,
    legacy_phase_word,
    magnitude_span_db,
    nearest_vector_word,
    pack_channel_words,
    pack_group_codes,
    phase_table,
    rx_beam_words,
    unpack_channel_words,
    unpack_group_codes,
    vector_from_word,
)


class BeamformerV3ArchitectureTests(unittest.TestCase):
    def test_every_raw_word_keeps_all_fifteen_unit_slices_active(self) -> None:
        self.assertEqual(sum(GROUP_WEIGHTS), 15)
        for word in range(256):
            self.assertEqual(accounted_unit_slices(word), TOTAL_UNIT_SLICES)
            self.assertEqual(len(unpack_group_codes(word)), 4)

    def test_constellation_has_256_unique_nonzero_points(self) -> None:
        points = constellation()
        self.assertEqual(len(points), 256)
        self.assertNotIn((0, 0), points)
        self.assertEqual(set(points.values()), set(range(256)))

    def test_group_and_channel_packets_round_trip(self) -> None:
        for word in range(256):
            self.assertEqual(pack_group_codes(unpack_group_codes(word)), word)
        words = (0x00, 0x55, 0xAA, 0xFF)
        packet = pack_channel_words(words)
        self.assertEqual(packet, 0xFFAA5500)
        self.assertEqual(unpack_channel_words(packet), words)

    def test_legacy_cardinal_words_exactly_match_v2_phase_alphabet(self) -> None:
        for phase_code, axis in enumerate(AXIS_VECTORS):
            word = legacy_phase_word(phase_code)
            value = vector_from_word(word)
            self.assertAlmostEqual(value.real, (TOTAL_UNIT_SLICES * axis).real)
            self.assertAlmostEqual(value.imag, (TOTAL_UNIT_SLICES * axis).imag)

    def test_eight_state_table_meets_architecture_quantization_gate(self) -> None:
        table = phase_table(8)
        self.assertEqual(len(table), 8)
        self.assertEqual(len({entry.word for entry in table}), 8)
        self.assertLessEqual(max(abs(entry.phase_error_deg) for entry in table), 4.0)
        self.assertLessEqual(magnitude_span_db(table), 0.35)

    def test_sixteen_state_table_remains_a_bounded_stretch_option(self) -> None:
        table = phase_table(16)
        self.assertEqual(len(table), 16)
        self.assertLessEqual(max(abs(entry.phase_error_deg) for entry in table), 4.0)
        self.assertLessEqual(magnitude_span_db(table), 0.90)

    def test_even_eight_state_beams_retain_four_ideal_dft_directions(self) -> None:
        matrix = beam_response_matrix(8)
        even = (0, 2, 4, 6)
        for selected in even:
            for incident in even:
                response = abs(matrix[selected][incident])
                if selected == incident:
                    self.assertAlmostEqual(response, CHANNEL_COUNT, places=12)
                else:
                    self.assertLess(response, 1e-12)

    def test_all_eight_beams_constructively_select_their_ideal_vector(self) -> None:
        matrix = beam_response_matrix(8)
        for beam in range(8):
            self.assertGreater(abs(matrix[beam][beam]), 3.95)

    def test_inner_constellation_points_support_amplitude_taper(self) -> None:
        full_word = nearest_vector_word(11.0 + 0.0j)
        half_word = nearest_vector_word(5.5 + 0.0j)
        self.assertLess(abs(vector_from_word(half_word)), abs(vector_from_word(full_word)))
        taper_db = 20.0 * math.log10(
            abs(vector_from_word(full_word)) / abs(vector_from_word(half_word))
        )
        self.assertGreater(taper_db, 5.0)

    def test_continuous_angle_response_peaks_near_broadside_for_beam_zero(self) -> None:
        words = rx_beam_words(0)
        broadside = abs(array_response(0.0, words))
        off_axis = abs(array_response(30.0, words))
        self.assertAlmostEqual(broadside, CHANNEL_COUNT, places=12)
        self.assertLess(off_axis, broadside)

    def test_invalid_packet_and_vector_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            unpack_group_codes(256)
        with self.assertRaises(ValueError):
            pack_group_codes((0, 1, 2))
        with self.assertRaises(ValueError):
            nearest_vector_word(16.0 + 0.0j)
        with self.assertRaises(ValueError):
            pack_channel_words((0, 1, 2))


if __name__ == "__main__":
    unittest.main()
