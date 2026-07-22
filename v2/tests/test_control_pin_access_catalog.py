import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "tools"))

from build_control_pin_access_catalog import ACCESS_MARGIN, build, contains, transform_rect


class ControlPinAccessCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads((ROOT / "build/v2/control_mapping/physical_netlist.json").read_text())
        cls.placement = json.loads((ROOT / "build/v2/control_placement/control_placement.json").read_text())
        cls.catalog = build(cls.mapping, cls.placement, ROOT)

    def test_every_signal_pin_has_legal_orientation_aware_access(self) -> None:
        self.assertEqual(self.catalog["status"], "pass", self.catalog["errors"])
        self.assertEqual(self.catalog["record_count"], 719)
        self.assertTrue(all(item["selected_access"]["inside_inset_lef_port"] for item in self.catalog["records"]))

    def test_li_candidates_keep_contact_inside_named_pin(self) -> None:
        for record in self.catalog["records"]:
            for access in record["legal_access_rects"]:
                margin = ACCESS_MARGIN.get(access["layer"], 0.0)
                for point in access["candidate_points_um"]:
                    self.assertTrue(contains(access["rect_um"], point, margin), (record, access, point))

    def test_or2b_mx_pin_rejects_the_previously_bad_lower_escape(self) -> None:
        instance = "core/$abc$549$auto$blifparse.cc:396:parse_blif$579"
        record = next(item for item in self.catalog["records"] if item["instance"] == instance and item["pin"] == "A")
        self.assertEqual(record["orientation"], "MX")
        self.assertTrue(any(contains(item["rect_um"], [152.0175, 179.99], 0.085) for item in record["legal_access_rects"]))
        self.assertFalse(any(contains(item["rect_um"], [152.0175, 179.70], 0.085) for item in record["legal_access_rects"]))

    def test_rectangle_transform_handles_all_legal_row_orientations(self) -> None:
        rect = [0.1, 0.2, 0.4, 0.6]
        self.assertEqual(transform_rect(rect, 2.0, 1.0, "R0"), rect)
        self.assertEqual(transform_rect(rect, 2.0, 1.0, "MX"), [0.1, 0.4, 0.4, 0.8])
        self.assertEqual(transform_rect(rect, 2.0, 1.0, "MY"), [1.6, 0.2, 1.9, 0.6])
        self.assertEqual(transform_rect(rect, 2.0, 1.0, "R180"), [1.6, 0.4, 1.9, 0.8])


if __name__ == "__main__":
    unittest.main()
