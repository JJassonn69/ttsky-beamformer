import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "v2" / "tools" / "generate_control_qrouter_inputs.py"
SPEC = importlib.util.spec_from_file_location("generate_control_qrouter_inputs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ControlQrouterInputTest(unittest.TestCase):
    def test_internal_nets_are_partitioned_and_bounded(self):
        placement = json.loads((ROOT / "build/v2/control_placement/control_placement.json").read_text())
        allocation = json.loads((ROOT / "build/v2/control_routing/control_route_allocation.json").read_text())
        power = json.loads((ROOT / "build/v2/control_power/control_power_geometry.json").read_text())
        power_plan = json.loads((ROOT / "v2/layout/control_power_plan.json").read_text())
        integration = json.loads((ROOT / "v2/layout/integration_plan.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tech = root / "tech.tlef"
            cells = root / "cells.lef"
            tech.write_text("technology\n")
            cells.write_text("cells\n")
            result = MODULE.generate(
                placement, allocation, power, power_plan, integration, tech, cells, root / "jobs"
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["total_internal_nets"], 150)
            self.assertEqual(result["local_pair_preroute_count"], 42)
            self.assertEqual(result["qrouter_net_count"], 108)
            self.assertEqual(sum(job["net_count"] for job in result["jobs"]), 108)
            self.assertEqual(
                result["qrouter_net_count"] + result["local_pair_preroute_count"],
                result["total_internal_nets"],
            )
            self.assertGreater(sum(job["blockage_count"] for job in result["jobs"]), 0)
            self.assertEqual({job["region"] for job in result["jobs"]}, {
                "global_control_core", "phase_configuration_bank", "trim_configuration_bank"
            })
            for job in result["jobs"]:
                text = Path(job["def"]).read_text()
                self.assertIn("DIEAREA ( 0 0 )", text)
                self.assertEqual(text.count("\nTRACKS "), 5)
                self.assertEqual(text.count("\n ;\n"), job["net_count"])
                self.assertIn(f"NETS {job['net_count']} ;", text)
                self.assertIn(f"BLOCKAGES {job['blockage_count']} ;", text)
                self.assertNotIn(" - LAYER ", text)
                self.assertEqual(text.count("\n END\n"), job["blockage_count"])
                self.assertNotIn("met5", text)
                config = Path(job["config"]).read_text()
                self.assertIn("Num_layers 5", config)
                self.assertIn("Layer_1_name li1", config)
                self.assertIn("Layer_5_name met4", config)


if __name__ == "__main__":
    unittest.main()
