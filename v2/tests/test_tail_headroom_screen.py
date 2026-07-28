import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_tail_headroom_screen import (
    CORNERS,
    conservative_node_proxies,
    proxy_trim_code,
    summarize,
    validate_screen_timing,
)


class TailHeadroomScreenTests(unittest.TestCase):
    def test_fixed_bank_proxy_mapping_preserves_active_count(self) -> None:
        self.assertEqual(proxy_trim_code(32), 4)
        self.assertEqual(proxy_trim_code(33), 5)
        self.assertEqual(proxy_trim_code(34), 6)
        for fixed in (32, 33, 34):
            self.assertEqual(fixed + 8, 36 + proxy_trim_code(fixed))

    def test_unsupported_proxy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            proxy_trim_code(27)
        with self.assertRaises(ValueError):
            proxy_trim_code(44)

    def test_screen_cannot_measure_unsettled_trim_programming(self) -> None:
        validate_screen_timing()
        with self.assertRaises(ValueError):
            validate_screen_timing(1.0, 2.0)
        with self.assertRaises(ValueError):
            validate_screen_timing(2.0, 2.5)

    def test_summary_requires_every_screen_corner_and_hard_cm_gate(self) -> None:
        records = []
        for corner in CORNERS:
            records.append({
                "proposed_fixed_units": 32,
                "corner": corner.name,
                "status": "pass",
                "output_common_mode_v": 0.9,
            })
        summary = summarize(records)
        self.assertEqual(summary["view"], "base")
        candidate = summary["candidates"][0]
        self.assertTrue(candidate["ready_for_device_region_check"])
        records[-1]["output_common_mode_v"] = 0.79
        candidate = summarize(records)["candidates"][0]
        self.assertFalse(candidate["ready_for_device_region_check"])

    def test_node_proxies_are_conservative_and_supply_aware(self) -> None:
        measurements = {
            "core_output_p_min": 0.7,
            "core_output_p_max": 1.1,
            "core_output_n_min": 0.72,
            "core_output_n_max": 1.08,
        }
        for channel in range(4):
            measurements.update({
                f"ch{channel}_gm_p_min": 0.51 + channel * 0.01,
                f"ch{channel}_gm_p_max": 0.9,
                f"ch{channel}_gm_n_min": 0.52 + channel * 0.01,
                f"ch{channel}_gm_n_max": 0.9,
                f"ch{channel}_tail_min": 0.40 + channel * 0.01,
                f"ch{channel}_tail_max": 0.42 + channel * 0.01,
                f"ch{channel}_gm_p_vds_min": 0.10 + channel * 0.01,
                f"ch{channel}_gm_n_vds_min": 0.11 + channel * 0.01,
            })
        proxies = conservative_node_proxies(measurements, 1.8)
        self.assertAlmostEqual(proxies["minimum_gm_drain_to_tail_v"], 0.09)
        self.assertAlmostEqual(proxies["minimum_tail_drain_to_ground_v"], 0.40)
        self.assertAlmostEqual(
            proxies["minimum_core_output_rail_clearance_v"], 0.7
        )
        self.assertAlmostEqual(
            proxies["minimum_time_aligned_gm_drain_to_tail_v"], 0.10
        )


if __name__ == "__main__":
    unittest.main()
