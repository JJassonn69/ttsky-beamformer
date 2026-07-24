import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_startup import deck_text


class ControlPostlayoutStartupTests(unittest.TestCase):
    def test_quiet_startup_deck_is_hash_bound_and_does_not_toggle_clocks(self) -> None:
        deck = deck_text(
            Path("build/v2/control_routing/final_rc/control_final_rc.spice"),
            "a" * 64,
            "b" * 64,
        )
        self.assertIn("extracted_netlist_sha256=" + "a" * 64, deck)
        self.assertIn("final_gds_sha256=" + "b" * 64, deck)
        self.assertIn("VSTART_", deck)
        self.assertIn("pwl(0 0 20n {VDD})", deck)
        self.assertNotIn("100u 200u", deck)
        self.assertNotIn("pulse(0 {VDD} 100n", deck)
        self.assertNotIn("phase0_", deck)
        self.assertEqual(deck.count(".save "), 1)
        self.assertIn("vcm_valid_settled", deck)
        self.assertIn("vcm_near_nominal_settled", deck)

    def test_quiet_startup_window_validation(self) -> None:
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", stop_us=4, final_window_us=4)
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", step_ns=0.5)


if __name__ == "__main__":
    unittest.main()
