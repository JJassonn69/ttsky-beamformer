from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
sys.path.insert(0, str(ROOT / "v3/tools"))
sys.path.insert(0, str(ROOT / "tools"))

from assemble_control_placement_gds import (  # noqa: E402
    ENDEL,
    STRNAME,
    record_type,
    records,
    split_library,
    structure_name,
)
from check_gds_flat_rules import parse_gds  # noqa: E402
from generate_submission_gds import (  # noqa: E402
    MET4_DRAW,
    MET4_PIN,
    PRBOUNDARY,
    package,
    package_without_project_boundary,
)
from check_submission_contract import (  # noqa: E402
    EXPECTED_ANALOG_PINS,
    EXPECTED_LAYER_PAIRS,
    analog_adjacency,
    raw_layer_pairs,
)
from template_pins import submission_pins  # noqa: E402


PLAN = ROOT / "v3/layout/submission_packaging_plan.json"
OUTPUT = ROOT / "build/v3/submission/tt_um_jjassonn69_beamformer.gds"
REPORT = ROOT / "build/v3/submission/gds_packaging.json"
TOP = "tt_um_jjassonn69_beamformer"
CONTRACT_REPORT = ROOT / "v3/frozen/submission/official_contract.json"
FROZEN_GDS = ROOT / f"v3/frozen/submission/{TOP}.gds"
SUBMISSION_GATE = ROOT / "v3/evidence/submission_gate.json"
MAGIC_EXTRACTED_PREBOUNDARY_SHA256 = "0226f6da17aa037bcc147c1726c8b1baa01d70c1954981feec709e8475edeee9"
TEXT = 0x0C
LAYER = 0x0D
TEXTTYPE = 0x16
XY = 0x10
STRING = 0x19


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bbox_nm(polygon: list[tuple[int, int]], database_um: float) -> tuple[int, int, int, int]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return tuple(
        round(value * database_um * 1000)
        for value in (min(xs), min(ys), max(xs), max(ys))
    )


def text_records(structure: list[bytes]) -> list[tuple[str, int, int, tuple[int, int]]]:
    result = []
    current: dict[str, object] | None = None
    for record in structure:
        kind = record_type(record)
        payload = record[4:]
        if kind == TEXT:
            current = {"name": "", "layer": -1, "texttype": -1, "xy": (0, 0)}
        elif current is not None and kind == LAYER:
            current["layer"] = struct.unpack(">h", payload)[0]
        elif current is not None and kind == TEXTTYPE:
            current["texttype"] = struct.unpack(">h", payload)[0]
        elif current is not None and kind == XY:
            current["xy"] = struct.unpack(">ii", payload)
        elif current is not None and kind == STRING:
            current["name"] = payload.rstrip(b"\0").decode("ascii")
        elif current is not None and kind == ENDEL:
            result.append((
                str(current["name"]), int(current["layer"]),
                int(current["texttype"]), tuple(current["xy"]),
            ))
            current = None
    return result


class V3SubmissionPackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.template = ROOT / self.plan["template"]["def"]
        self.width_nm, self.height_nm, self.pins = submission_pins(self.template)

    def test_packaging_is_deterministic_and_bound_to_frozen_source(self) -> None:
        expected, report = package(PLAN)
        self.assertEqual(OUTPUT.read_bytes(), expected)
        repeated, repeated_report = package(PLAN)
        self.assertEqual(repeated, expected)
        self.assertEqual(repeated_report, report)
        source = self.plan["source_checkpoint"]
        self.assertEqual(sha256(ROOT / source["gds"]), source["sha256"])
        self.assertEqual(sha256(ROOT / source["physical_gate"]), source["physical_gate_sha256"])
        self.assertEqual(report["source_sha256"], source["sha256"])
        self.assertEqual(report["submission_sha256"], sha256(OUTPUT))
        self.assertEqual(report["changed_existing_gds_records"], 3)
        self.assertEqual(report["removed_redundant_internal_power_labels"], 2)
        self.assertEqual(report["added_project_boundary_polygons"], 1)
        self.assertEqual(
            report["magic_extracted_preboundary_sha256"],
            MAGIC_EXTRACTED_PREBOUNDARY_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(package_without_project_boundary(PLAN)).hexdigest(),
            MAGIC_EXTRACTED_PREBOUNDARY_SHA256,
        )
        self.assertTrue(report["project_boundary_is_non_electrical_only_delta"])
        self.assertEqual(report["added_signal_drawing_polygons"], 51)
        self.assertEqual(report["added_pin_purpose_polygons"], 53)
        self.assertEqual(report["ensured_top_level_interface_labels"], 53)
        self.assertEqual(report["added_top_level_labels"], 51)

    def test_exact_official_pin_shapes_and_labels_are_present(self) -> None:
        structures, database_um = parse_gds(OUTPUT)
        top = structures[TOP]
        project_boundaries = [
            bbox_nm(polygon, database_um)
            for layer, polygon in top.polygons if layer == PRBOUNDARY
        ]
        self.assertEqual(project_boundaries, [(0, 0, self.width_nm, self.height_nm)])
        pin_rectangles = [
            bbox_nm(polygon, database_um)
            for layer, polygon in top.polygons if layer == MET4_PIN
        ]
        expected_all = {pin.rect_nm for pin in self.pins}
        self.assertEqual(len(pin_rectangles), 53)
        self.assertEqual(set(pin_rectangles), expected_all)
        drawing_rectangles = {
            bbox_nm(polygon, database_um)
            for layer, polygon in top.polygons if layer == MET4_DRAW
        }
        expected_signal = {pin.rect_nm for pin in self.pins if pin.use == "SIGNAL"}
        self.assertTrue(expected_signal <= drawing_rectangles)

        _header, raw_structures, _endlib = split_library(records(OUTPUT.read_bytes()))
        raw_top = next(item for item in raw_structures if structure_name(item) == TOP)
        labels = text_records(raw_top)
        official_names = {pin.name for pin in self.pins}
        for pin in self.pins:
            lx, by, rx, ty = pin.rect_nm
            expected = (pin.name, 71, 5, ((lx + rx) // 2, (by + ty) // 2))
            self.assertEqual(labels.count(expected), 1, pin.name)
        for name in ("VDPWR", "VGND"):
            self.assertEqual(sum(label[0] == name for label in labels), 1, name)

    def test_top_name_lef_verilog_and_metadata_contract(self) -> None:
        _header, structures, _endlib = split_library(records(OUTPUT.read_bytes()))
        names = [structure_name(item) for item in structures]
        self.assertEqual(names.count(TOP), 1)
        self.assertNotIn(self.plan["source_checkpoint"]["top"], names)
        lef = (ROOT / f"lef/{TOP}.lef").read_text(encoding="utf-8")
        self.assertIn(f"MACRO {TOP}", lef)
        self.assertIn("SIZE 334.880 BY 225.760 ;", lef)
        self.assertEqual(len(re.findall(r"^\s*PIN \S+", lef, re.MULTILINE)), 53)
        verilog = (ROOT / "src/project.v").read_text(encoding="utf-8")
        self.assertIn(f"module {TOP}", verilog)
        self.assertIn("assign uo_out  = 8'b0;", verilog)
        self.assertIn("assign uio_out = 8'b0;", verilog)
        self.assertIn("assign uio_oe  = 8'b0;", verilog)
        info = (ROOT / "info.yaml").read_text(encoding="utf-8")
        for fragment in (
            'clock_hz:     16000000', 'tiles:        "2x2"',
            'analog_pins:  6', 'uses_vapwr:   false',
            'ui[2]: "BEAM_SELECT_2"', 'ui[3]: "RAW_VECTOR_MODE"',
        ):
            self.assertIn(fragment, info)

    def test_local_official_wrapper_mirror_is_current_and_clean(self) -> None:
        contract = json.loads(CONTRACT_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(contract["status"], "pass", contract["errors"])
        self.assertEqual(contract["gds_sha256"], sha256(OUTPUT))
        self.assertTrue(contract["checks"]["unique_top"])
        self.assertEqual(
            contract["checks"]["top_bbox_dbu"],
            [0, 0, self.width_nm, self.height_nm],
        )
        self.assertEqual(
            contract["checks"]["prboundary_bbox_dbu"],
            [0, 0, self.width_nm, self.height_nm],
        )
        self.assertTrue(contract["checks"]["exact_lef_ports"])
        self.assertTrue(contract["checks"]["exact_gds_pin_purpose_shapes"])
        self.assertEqual(contract["checks"]["nwell_urpm_markers"], 0)
        self.assertEqual(contract["checks"]["verilog_syntax_exit"], 0)

    def test_analog_pin_adjacency_and_layer_population_match_policy(self) -> None:
        observed = analog_adjacency(OUTPUT)
        expected = {
            f"ua[{index}]": index < EXPECTED_ANALOG_PINS for index in range(8)
        }
        self.assertEqual(observed, expected)
        self.assertEqual(raw_layer_pairs(OUTPUT), EXPECTED_LAYER_PAIRS)

    def test_internal_submission_gate_and_promoted_artifacts_are_current(self) -> None:
        gate = json.loads(SUBMISSION_GATE.read_text(encoding="utf-8"))
        self.assertEqual(
            gate["status"],
            "internal_signoff_pass_official_github_precheck_pending",
        )
        self.assertEqual(gate["errors"], [])
        self.assertEqual(gate["gds_sha256"], sha256(OUTPUT))
        self.assertEqual(sha256(FROZEN_GDS), sha256(OUTPUT))
        self.assertEqual(sha256(ROOT / f"gds/{TOP}.gds"), sha256(OUTPUT))
        self.assertTrue(all(gate["electrical_signoff"]["gates"].values()))
        self.assertTrue(
            all(value == 0 for value in gate["physical_signoff"]["direct_gds_marker_groups"].values())
        )
        for path, expected_hash in gate["artifact_sha256"].items():
            self.assertEqual(sha256(ROOT / path), expected_hash, path)


if __name__ == "__main__":
    unittest.main()
