#!/usr/bin/env python3
"""Executable checks for the V3 vector-control RTL."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/model"))

from beamformer_v3 import pack_channel_words, rx_beam_words  # noqa: E402


class VectorControlRtlTests(unittest.TestCase):
    def test_rtl_lut_is_generated_from_the_golden_model(self) -> None:
        expected = {
            beam: pack_channel_words(rx_beam_words(beam))
            for beam in range(8)
        }
        for source in ("vector_control_core.v", "physical_control_core.v"):
            text = (ROOT / "v3/rtl" / source).read_text()
            found = {
                int(index): int(value, 16)
                for index, value in re.findall(
                    r"3'd([0-7]):\s+automatic_beam_words\s*=\s*32'h([0-9A-Fa-f]{8})",
                    text,
                )
            }
            self.assertEqual(found, expected, source)

    def test_iverilog_control_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tb.out"
            compile_run = subprocess.run(
                [
                    "iverilog", "-g2012", "-o", str(output),
                    "v3/rtl/serial_config.v",
                    "v3/rtl/quadrature_generator.v",
                    "v3/rtl/vector_control_core.v",
                    "v3/rtl/tb_vector_control_core.v",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(compile_run.returncode, 0, compile_run.stdout)
            simulation = subprocess.run(
                ["vvp", str(output)], cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                timeout=20,
            )
            self.assertEqual(simulation.returncode, 0, simulation.stdout)
            self.assertIn("PASS: V3 LUT", simulation.stdout)

    def test_iverilog_physical_control_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tb_physical.out"
            compile_run = subprocess.run(
                [
                    "iverilog", "-g2012", "-o", str(output),
                    "v3/rtl/quadrature_generator.v",
                    "v3/rtl/physical_control_core.v",
                    "v3/rtl/tb_physical_control_core.v",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(compile_run.returncode, 0, compile_run.stdout)
            simulation = subprocess.run(
                ["vvp", str(output)], cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                timeout=20,
            )
            self.assertEqual(simulation.returncode, 0, simulation.stdout)
            self.assertIn("PASS: V3 physical-control", simulation.stdout)

    def test_iverilog_buffered_physical_mapping_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tb_physical_mapped.out"
            mapped_tb = Path(directory) / "tb_physical_mapped.v"
            mapped_tb.write_text(
                (ROOT / "v3/rtl/tb_physical_control_core.v").read_text().replace(
                    "v3_physical_control_core dut",
                    "v3_physical_control_core_mapped dut",
                )
            )
            compile_run = subprocess.run(
                [
                    "iverilog", "-g2012", "-o", str(output),
                    "v2/rtl/sky130_control_cells_sim.v",
                    "build/v3/control_mapping/physical_mapping.v",
                    str(mapped_tb),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(compile_run.returncode, 0, compile_run.stdout)
            simulation = subprocess.run(
                ["vvp", str(output)], cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=20,
            )
            self.assertEqual(simulation.returncode, 0, simulation.stdout)
            self.assertIn("PASS: V3 physical-control", simulation.stdout)


if __name__ == "__main__":
    unittest.main()
