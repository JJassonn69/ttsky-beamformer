import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from bind_noise_scope import bind


class NoiseScopeBindingTests(unittest.TestCase):
    def test_scope_is_bound_to_frozen_physical_artifacts(self) -> None:
        scope = json.loads((ROOT / "v2/evidence/noise_scope.json").read_text())
        contract = json.loads((ROOT / "v2/layout/vcm_varactor_eco.json").read_text())
        extraction = json.loads(
            (ROOT / "build/v2/control_routing/final_rc/coverage_audit.json").read_text()
        )
        self.assertEqual(scope, bind(scope, contract, extraction))


if __name__ == "__main__":
    unittest.main()
