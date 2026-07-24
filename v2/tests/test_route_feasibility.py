import json
import sys
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "tools"))

from check_route_feasibility import validate


class RouteFeasibilityTests(unittest.TestCase):
    def test_measured_terminal_spans_and_matching(self) -> None:
        def read(name: str):
            return json.loads((V2_ROOT / "layout" / name).read_text())

        report = validate(
            read("critical_routes.json"),
            read("channel_template.json"),
            read("pcell_dimensions.json"),
            read("port_catalog.json"),
        )
        self.assertEqual(report["status"], "pass", report["errors"])
        for match in report["matching_groups"].values():
            self.assertLessEqual(match["mismatch_percent"], match["limit_percent"])


if __name__ == "__main__":
    unittest.main()
