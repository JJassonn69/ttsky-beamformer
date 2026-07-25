#!/usr/bin/env python3
"""Structural guards for the V3 1/2/4/8 one-channel SPICE cell."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "v3/spice/vector_channel_15.inc").read_text()


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


if __name__ == "__main__":
    unittest.main()
