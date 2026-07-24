import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_gate5_twotone_pilot import twotone_deck


class Gate5TwotonePilotTests(unittest.TestCase):
    def test_deck_has_two_rf_tones_and_four_if_demodulators(self) -> None:
        netlist = ROOT / "build/v2/control_routing/final_rc/control_final_base.spice"
        deck = twotone_deck(netlist, "gds", "base", 0.002)
        self.assertEqual(deck.count("BVIN"), 4)
        self.assertFalse(any(line.startswith("VIN0 ") for line in deck.splitlines()))
        self.assertIn("F1=4.9meg F2=5.1meg VINTONE=0.002", deck)
        for name in ("im3_low", "fund_low", "fund_high", "im3_high"):
            self.assertIn(f".measure tran {name}_rms", deck)
        self.assertIn("from=5u to=10u", deck)


if __name__ == "__main__":
    unittest.main()
