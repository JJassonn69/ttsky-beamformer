#!/usr/bin/env python3
"""Structural guards for the V3 1/2/4/8 one-channel SPICE cell."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "v3/spice/vector_channel_15.inc").read_text()
sys.path.insert(0, str(ROOT / "v3" / "tools"))

import run_four_channel_support_pvt as support_pvt
import run_four_channel_support_sweep as support_sweep
import run_vcm_divider_tradeoff as divider_tradeoff


def subcircuit(name: str) -> str:
    match = re.search(
        rf"^\.subckt {name}\b(?P<body>.*?)^\.ends {name}$",
        TEXT,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing subcircuit {name}")
    return match.group("body")


class VectorSpiceTopologyTests(unittest.TestCase):
    def test_both_channel_views_contain_exactly_fifteen_units(self) -> None:
        ideal = re.findall(r"^XG([0-3])_([0-9]+)\b", subcircuit("v3_vector_channel_15"), re.MULTILINE)
        mos = re.findall(r"^XG([0-3])_([0-9]+)\b", subcircuit("v3_vector_channel_15_mos"), re.MULTILINE)
        expected = [(str(group), str(unit)) for group, count in enumerate((1, 2, 4, 8)) for unit in range(count)]
        self.assertEqual(ideal, expected)
        self.assertEqual(mos, expected)

    def test_mos_unit_has_one_tail_and_six_signal_devices(self) -> None:
        body = subcircuit("v3_vector_unit_mos")
        self.assertEqual(len(re.findall(r"^XGM_", body, re.MULTILINE)), 2)
        self.assertEqual(len(re.findall(r"^XSW_", body, re.MULTILINE)), 4)
        self.assertEqual(len(re.findall(r"^XTAIL\b", body, re.MULTILINE)), 1)

    def test_bias_blank_interface_is_a_real_pass_and_pulldown_pair(self) -> None:
        body = subcircuit("v3_bias_blank_switch")
        self.assertEqual(len(re.findall(r"^XPASS\b", body, re.MULTILINE)), 1)
        self.assertEqual(len(re.findall(r"^XPULL\b", body, re.MULTILINE)), 1)

    def test_provisional_geometry_preserves_v2_aggregate_widths(self) -> None:
        self.assertAlmostEqual(15 * 0.84, 12.60)
        self.assertAlmostEqual(15 * 5.066666666, 76.0, places=6)
        self.assertAlmostEqual(8 * 2 * 0.65, 10.4)

    def test_four_channel_support_deck_cannot_hide_ideal_common_mode_or_per_channel_loads(self) -> None:
        deck = support_sweep.deck(support_sweep.MODES[0], 2925.0, 2)
        self.assertEqual(len(re.findall(r"^XCHANNEL[0-3]\b", deck, re.MULTILINE)), 4)
        self.assertEqual(len(re.findall(r"^XRIN[0-3]\b", deck, re.MULTILINE)), 4)
        self.assertEqual(len(re.findall(r"^RLOAD[PN]\b", deck, re.MULTILINE)), 2)
        self.assertEqual(len(re.findall(r"^XRVCM_(?:TOP|BOTTOM)\b", deck, re.MULTILINE)), 2)
        self.assertNotRegex(deck, r"^V(?:CM|REF)\b")
        self.assertEqual(len(re.findall(r"^CVAR[0-1]\b", deck, re.MULTILINE)), 2)
        for index in range(4):
            source = re.search(rf"^VSRC{index} .*sin\(([^)]*)\)$", deck, re.MULTILINE)
            self.assertIsNotNone(source)
            self.assertEqual(len(source.group(1).split()), 6)

    def test_support_pvt_deck_checks_low_supply_physical_divider_headroom(self) -> None:
        corner = next(item for item in support_pvt.CORNERS if item.name == "ss_low_hot")
        deck = support_pvt.corner_deck(
            support_sweep.MODES[0], 2925.0, 2, 0, 0.25, corner
        )
        self.assertIn('sky130_1v8_ss.inc', deck)
        self.assertIn('.param VDD=1.62 ', deck)
        self.assertIn('.temp 85', deck)
        self.assertEqual(len(re.findall(r"^\.measure tran gm_[pn]_vds_min_[0-3]\b", deck, re.MULTILINE)), 8)

    def test_vcm_divider_tradeoff_uses_six_identical_two_to_four_units(self) -> None:
        deck = divider_tradeoff.tradeoff_deck(support_sweep.MODES[0], 2925.0, 0, 0.25)
        divider_lines = re.findall(r"^XRVCM_[TB][0-3].*$", deck, re.MULTILINE)
        self.assertEqual(len(divider_lines), 6)
        self.assertTrue(all("l=5.875" in line for line in divider_lines))
        self.assertEqual(sum(line.startswith("XRVCM_T") for line in divider_lines), 2)
        self.assertEqual(sum(line.startswith("XRVCM_B") for line in divider_lines), 4)


if __name__ == "__main__":
    unittest.main()
