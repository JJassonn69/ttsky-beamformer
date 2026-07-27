from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v3/tools"))

from build_four_channel_power_integration import build  # noqa: E402


class FourChannelPowerIntegrationTests(unittest.TestCase):
    def test_manifest_is_reproducible_and_hash_bound(self) -> None:
        manifest = json.loads(
            (ROOT / "v3/layout/four_channel_power_integration.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest, build())
        self.assertEqual(len(manifest["endpoints"]["VDPWR"]["channels"]), 4)
        self.assertEqual(len(manifest["endpoints"]["VGND"]["channels"]), 4)
        self.assertFalse(manifest["constraints"]["uses_vapwr"])
        self.assertTrue(manifest["routing_decisions"]["no_floating_stubs"])

        # This exact check catches DRC-clean electrical rail crossings, such as
        # the rejected M4 VDPWR spine across the orthogonal M4 VGND trunk.
        def bbox(record: dict[str, object]) -> tuple[float, float, float, float]:
            x1, y1 = record["from"]  # type: ignore[misc]
            x2, y2 = record["to"]  # type: ignore[misc]
            half = float(record["width_um"]) / 2.0
            return min(x1, x2) - half, min(y1, y2) - half, max(x1, x2) + half, max(y1, y2) + half

        def touches(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
            return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

        added: list[tuple[str, str, tuple[float, float, float, float], str]] = []
        for net, routes in manifest["routes"].items():
            for route in routes:
                added.append((net, route["layer"], bbox(route), route["role"]))
        for net, pin in manifest["external_power_pins"].items():
            added.append((net, pin["layer"], tuple(pin["bbox_um"]), "external_pin"))
        for net, points in manifest["via2_points_um"].items():
            for index, (x, y) in enumerate(points):
                added.append((net, "metal2", (x - .20, y - .20, x + .20, y + .20), f"via2_{index}_m2"))
                added.append((net, "metal3", (x - .31, y - .20, x + .31, y + .20), f"via2_{index}_m3"))
        for net, points in manifest["via3_points_um"].items():
            for index, (x, y) in enumerate(points):
                added.append((net, "metal3", (x - .31, y - .20, x + .31, y + .20), f"via3_{index}_m3"))
                added.append((net, "metal4", (x - .20, y - .20, x + .20, y + .20), f"via3_{index}_m4"))
        for index, first in enumerate(added):
            for second in added[index + 1:]:
                if first[0] != second[0] and first[1] == second[1]:
                    self.assertFalse(touches(first[2], second[2]), (first, second))

    def test_exact_power_gate_is_closed_when_evidence_exists(self) -> None:
        path = ROOT / "v3/evidence/four_channel_power_integration_gate.json"
        if not path.is_file():
            self.skipTest("exact shared-power GDS gate has not run yet")
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["checks"].values()), report["checks"])
        self.assertEqual(report["power_terminal_hits"], {"VDPWR": 740, "VGND": 1360})
        self.assertEqual(report["rail_equivalences"], [])


if __name__ == "__main__":
    unittest.main()
