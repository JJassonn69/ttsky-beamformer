import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_route_overlay_gds import assemble
from check_magic_rc_log import FATAL_PATTERNS


class RouteOverlayAssemblyTests(unittest.TestCase):
    source = (
        ROOT / "build/v2/control_routing/openroad_internal/direct/"
        "v2_control_internal_routed.gds"
    )
    overlay = (
        ROOT / "build/v2/control_routing/trim_overlay/direct/"
        "v2_control_trim_routes_overlay.gds"
    )
    output = ROOT / "build/v2/control_routing/direct/v2_control_trim_routed.gds"
    labels = {f"active_trim_codes[{index}]" for index in range(16)}

    def test_exact_trim_assembly_is_deterministic(self) -> None:
        data, report = assemble(
            self.source, "v2_control_internal_routed",
            self.overlay, "v2_control_trim_routes_overlay",
            "v2_control_trim_routed", self.labels,
        )
        self.assertEqual(data, self.output.read_bytes())
        self.assertEqual(set(report["top_level_labels_promoted"]), self.labels)
        self.assertEqual(report["overlay_reference_count_added"], 1)

    def test_exact_trim_gds_magic_import_is_clean(self) -> None:
        text = (
            ROOT / "build/v2/control_routing/direct/trim_magic_import_drc.log"
        ).read_text(errors="replace")
        self.assertIn("CONTROL_TRIM_DIRECT_GDS_DRC_COUNT=0", text)
        self.assertIn("CONTROL_TRIM_DIRECT_GDS_FEEDBACK_COUNT=0", text)
        for name, pattern in FATAL_PATTERNS.items():
            self.assertIsNone(pattern.search(text), name)


if __name__ == "__main__":
    unittest.main()
