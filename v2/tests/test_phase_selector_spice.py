import json
import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class V2PhaseSelectorSpiceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ngspice"), "ngspice is not installed")
    def test_phase_selector_nominal_and_30mhz(self) -> None:
        output = PROJECT_ROOT / "build" / "v2" / "phase_selector" / "test_summary.json"
        subprocess.run(
            ["python3", "v2/tools/run_phase_selector_sweep.py", "--output", str(output)],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
            timeout=180,
        )
        summary = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "pass", summary["failures"])
        self.assertEqual(summary["case_count"], 2)


if __name__ == "__main__":
    unittest.main()
