import unittest

from tools.run_core_pvt import evaluate
from tools.run_extracted_pvt import csv_values


class PvtCheckTests(unittest.TestCase):
    def test_targeted_pvt_overrides_parse_signed_temperature(self) -> None:
        self.assertEqual(csv_values("ss,ff", str, ("tt",)), ("ss", "ff"))
        self.assertEqual(csv_values("1.62", float, (1.80,)), (1.62,))
        self.assertEqual(csv_values("-40,125", int, (27,)), (-40, 125))

    def test_targeted_pvt_override_rejects_empty_list(self) -> None:
        with self.assertRaises(ValueError):
            csv_values(",", int, (27,))

    def test_common_mode_uses_active_supply_headroom(self) -> None:
        values = {
            "sum_rms": 20e-3,
            "null_rms": 50e-6,
            "sum_cm": 1.84,
            "null_cm": 1.83,
            "sum_supply": -250e-6,
            "null_supply": -249e-6,
        }
        derived, checks = evaluate(values, supply_v=1.98)
        self.assertAlmostEqual(derived["output_high_headroom_v"], 0.14)
        self.assertTrue(checks["common_mode"])

    def test_common_mode_rejects_insufficient_headroom(self) -> None:
        values = {
            "sum_rms": 20e-3,
            "null_rms": 50e-6,
            "sum_cm": 1.84,
            "null_cm": 1.83,
            "sum_supply": -250e-6,
            "null_supply": -249e-6,
        }
        _derived, checks = evaluate(values, supply_v=1.90)
        self.assertFalse(checks["common_mode"])


if __name__ == "__main__":
    unittest.main()
