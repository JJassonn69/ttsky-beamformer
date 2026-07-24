import json
import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = PROJECT_ROOT / "third_party" / "sky130_fd_pr"
SUMMARY = PROJECT_ROOT / "build" / "v2" / "r2r" / "unittest_summary.json"


class V2R2RSpiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ngspice") and MODEL_ROOT.exists(), "SKY130 ngspice models are required")
    def test_r2r_quick_sweep(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "v2/tools/run_r2r_sweep.py",
                "--output",
                str(SUMMARY),
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["case_count"], 2)
        self.assertTrue(all(case["monotonic"] for case in summary["cases"]))


if __name__ == "__main__":
    unittest.main()
