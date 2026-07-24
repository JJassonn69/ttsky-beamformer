import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
SCRIPT = ROOT / "v2" / "tools" / "generate_control_openroad_inputs.py"
SPEC = importlib.util.spec_from_file_location("generate_control_openroad_inputs", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ControlOpenroadInputTest(unittest.TestCase):
    def test_every_internal_net_is_owned_by_openroad(self):
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
                placement, allocation, power, power_plan, integration,
                tech, cells, root / "jobs",
            )

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["backend"], "openroad")
            self.assertEqual(result["total_internal_nets"], 206)
            self.assertEqual(result["router_net_count"], 206)
            self.assertEqual(result["openroad_net_count"], 206)
            self.assertEqual(result["local_pair_preroute_count"], 0)
            self.assertEqual(sum(job["net_count"] for job in result["jobs"]), 206)
            self.assertEqual(sum(job["top_pin_count"] for job in result["jobs"]), 45)
            self.assertEqual(len(result["jobs"]), 1)
            for job in result["jobs"]:
                def_text = Path(job["def"]).read_text()
                self.assertIn(" - LAYER ", def_text)
                self.assertNotIn("\n END\n", def_text)
                self.assertEqual(def_text.count("\nTRACKS "), 10)
                self.assertEqual(def_text.count("\n ;\n"), job["net_count"])
                self.assertNotIn("met5", def_text)
                route_tcl = Path(job["script"]).read_text()
                self.assertIn("global_route", route_tcl)
                self.assertIn("detailed_route", route_tcl)
                self.assertIn("met1-met4", route_tcl)
                self.assertNotIn("met5", route_tcl)
                for pin in job["top_pins"].values():
                    for coordinate, delta in zip(
                        pin["point_um"] * 2,
                        pin["rect_um"],
                    ):
                        self.assertEqual(
                            round((coordinate + delta) * 1000) % 5,
                            0,
                            f"{pin} is off the 5 nm manufacturing grid",
                        )
            digital_job = next(
                job for job in result["jobs"]
                if job["region"] == "digital_control"
            )
            digital_def = Path(digital_job["def"]).read_text()
            self.assertIn("PINS 45 ;", digital_def)
            self.assertEqual(digital_def.count("( PIN Q"), 4)
            self.assertEqual(digital_def.count("( PIN T"), 16)
            self.assertEqual(digital_def.count("( PIN S_"), 4)
            self.assertEqual(digital_def.count("( PIN I_"), 9)
            self.assertEqual(digital_def.count("( PIN P"), 12)
            self.assertEqual(digital_job["net_count"], 206)
            self.assertEqual(sum(job["endpoint_count"] for job in result["jobs"]), 763)


if __name__ == "__main__":
    unittest.main()
