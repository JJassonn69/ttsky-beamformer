import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RTL_ROOT = PROJECT_ROOT / "v2" / "rtl"
BUILD_ROOT = PROJECT_ROOT / "build" / "v2"


class V2ControlRTLTests(unittest.TestCase):
    def run_testbench(self, top: str, sources: list[str]) -> str:
        BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        executable = BUILD_ROOT / f"{top}.vvp"
        compile_result = subprocess.run(
            [
                "iverilog", "-g2012", "-s", top, "-o", str(executable),
                *(str(RTL_ROOT / source) for source in sources),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        simulation = subprocess.run(
            ["vvp", str(executable)],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(simulation.returncode, 0, simulation.stdout + simulation.stderr)
        return simulation.stdout

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "iverilog is required")
    def test_control_core(self) -> None:
        output = self.run_testbench("tb_control_core", [
            "quadrature_generator.v", "serial_config.v", "control_core.v",
            "tb_control_core.v",
        ])
        self.assertIn("PASS:", output)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "iverilog is required")
    def test_physical_control_core(self) -> None:
        output = self.run_testbench("tb_physical_control_core", [
            "quadrature_generator.v", "physical_control_core.v",
            "tb_physical_control_core.v",
        ])
        self.assertIn("PASS: physical RX codebook", output)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "iverilog is required")
    def test_mapped_physical_control_core(self) -> None:
        mapped = BUILD_ROOT / "control_mapping" / "physical_netlist.v"
        self.assertTrue(mapped.is_file(), "run v2/tools/map_control_netlist.py --verilog")
        executable = BUILD_ROOT / "tb_physical_control_mapped.vvp"
        sources = [
            RTL_ROOT / "quadrature_generator.v",
            RTL_ROOT / "physical_control_core.v",
            RTL_ROOT / "sky130_control_cells_sim.v",
            mapped,
            RTL_ROOT / "tb_physical_control_mapped.v",
        ]
        compile_result = subprocess.run(
            ["iverilog", "-g2012", "-s", "tb_physical_control_mapped", "-o", str(executable), *map(str, sources)],
            cwd=PROJECT_ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        simulation = subprocess.run(
            ["vvp", str(executable)], cwd=PROJECT_ROOT, text=True,
            capture_output=True, check=False, timeout=10,
        )
        self.assertEqual(simulation.returncode, 0, simulation.stdout + simulation.stderr)
        self.assertIn("PASS: mapped SKY130 control netlist", simulation.stdout)


if __name__ == "__main__":
    unittest.main()
