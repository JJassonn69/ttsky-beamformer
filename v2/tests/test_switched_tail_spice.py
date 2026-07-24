import json
import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class V2SwitchedTailSpiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ngspice"), "ngspice is not installed")
    def test_switched_tail_quick_sweep(self) -> None:
        output = PROJECT_ROOT / "build" / "v2" / "switched_tail" / "test_summary.json"
        subprocess.run(
            [
                "python3",
                "v2/tools/run_switched_tail_sweep.py",
                "--output",
                str(output),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
            timeout=60,
        )
        summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "pass", summary["failures"])
        case = summary["cases"][0]
        self.assertAlmostEqual(case["code_0_relative"], 32.0 / 40.0, places=4)
        self.assertAlmostEqual(case["code_8_relative"], 1.00, places=6)
        self.assertAlmostEqual(case["code_15_relative"], 47.0 / 40.0, places=4)


if __name__ == "__main__":
    unittest.main()
