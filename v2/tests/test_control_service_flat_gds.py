import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from check_gds_flat_rules import (
    MCON, VIA1, VIA2, VIA3, audit_rectangles, flatten_rectangles, parse_gds,
)


class ControlFinalFlatGdsTest(unittest.TestCase):
    def test_exact_final_gds_has_no_stub_or_cut_geometry_regression(self) -> None:
        candidate = (
            ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
        )
        structures, database_um = parse_gds(candidate)
        rectangles = flatten_rectangles(
            structures, "v2_control_quadrature_routed", database_um
        )
        _components, checks = audit_rectangles(rectangles)
        for rule in (
            "met3 spacing", "met4 spacing", "met4 minimum area",
            "via3 enclosure", "via-only met3 island",
            "capm-to-unrelated-met3 spacing",
        ):
            self.assertEqual(checks[rule], [], rule)
        # One legacy M4-width marker is inherited unchanged from the powered
        # source; the independent full-deck delta test proves it is not added
        # by any current route overlay.
        self.assertEqual(len(checks["met4 minimum width"]), 1)

        expected_cut_size = {MCON: 0.17, VIA1: 0.15, VIA2: 0.20, VIA3: 0.20}
        for layer, size in expected_cut_size.items():
            self.assertGreater(len(rectangles[layer]), 0)
            for x0, y0, x1, y1 in rectangles[layer]:
                self.assertAlmostEqual(x1 - x0, size, places=6)
                self.assertAlmostEqual(y1 - y0, size, places=6)

        delta = json.loads(
            (ROOT / "build/v2/control_routing/direct/"
             "final_klayout_delta_audit.json").read_text()
        )
        self.assertEqual(delta["status"], "pass")
        self.assertEqual(
            delta["candidate_gds_sha256"],
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
