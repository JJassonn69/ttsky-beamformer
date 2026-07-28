#!/usr/bin/env python3
"""Package the frozen V3 electrical top as the official TinyTapeout macro."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from assemble_control_placement_gds import (  # noqa: E402
    ASCII,
    ENDSTR,
    ENDEL,
    INT4,
    NODATA,
    SNAME,
    STRNAME,
    XY,
    ascii_record,
    make_record,
    record_type,
    records,
    split_library,
    structure_name,
)
from template_pins import submission_pins  # noqa: E402


BOUNDARY = 0x08
TEXT = 0x0C
LAYER = 0x0D
DATATYPE = 0x0E
TEXTTYPE = 0x16
STRING = 0x19
INT2 = 0x02
MET4_DRAW = (71, 20)
MET4_PIN = (71, 16)
MET4_TEXTTYPE = 5
PRBOUNDARY = (235, 4)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def rectangle_boundary(layer: tuple[int, int], rect_nm: tuple[int, int, int, int]) -> list[bytes]:
    lx, by, rx, ty = rect_nm
    points = (lx, by, rx, by, rx, ty, lx, ty, lx, by)
    return [
        make_record(BOUNDARY, NODATA),
        make_record(LAYER, INT2, struct.pack(">h", layer[0])),
        make_record(DATATYPE, INT2, struct.pack(">h", layer[1])),
        make_record(XY, INT4, struct.pack(">10i", *points)),
        make_record(ENDEL, NODATA),
    ]


def text_element(name: str, rect_nm: tuple[int, int, int, int]) -> list[bytes]:
    lx, by, rx, ty = rect_nm
    x, y = (lx + rx) // 2, (by + ty) // 2
    return [
        make_record(TEXT, NODATA),
        make_record(LAYER, INT2, struct.pack(">h", MET4_DRAW[0])),
        make_record(TEXTTYPE, INT2, struct.pack(">h", MET4_TEXTTYPE)),
        make_record(XY, INT4, struct.pack(">ii", x, y)),
        make_record(STRING, ASCII, name.encode("ascii")),
        make_record(ENDEL, NODATA),
    ]


def existing_text_keys(structure: list[bytes]) -> set[tuple[str, int, int, tuple[int, int]]]:
    result: set[tuple[str, int, int, tuple[int, int]]] = set()
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
            result.add((
                str(current["name"]), int(current["layer"]),
                int(current["texttype"]), tuple(current["xy"]),
            ))
            current = None
    return result


def remove_nonofficial_power_labels(
    structure: list[bytes],
    official_keys: dict[str, tuple[str, int, int, tuple[int, int]]],
) -> tuple[list[bytes], int]:
    """Remove only redundant top-level VDPWR/VGND text elements.

    The frozen electrical source carries useful internal supply labels in
    addition to the official boundary labels.  Once pin-purpose geometry is
    added, Magic treats those repeated names as ambiguous ports.  Retaining
    the boundary label and dropping the redundant internal text does not
    alter any conductor geometry or connectivity.
    """

    filtered: list[bytes] = []
    removed = 0
    index = 0
    while index < len(structure):
        if record_type(structure[index]) != TEXT:
            filtered.append(structure[index])
            index += 1
            continue
        end = index
        while end < len(structure) and record_type(structure[end]) != ENDEL:
            end += 1
        if end >= len(structure):
            raise ValueError("unterminated TEXT element in submission source top")
        element = structure[index : end + 1]
        keys = existing_text_keys(element)
        if len(keys) != 1:
            raise ValueError("could not decode one submission-source TEXT element")
        key = next(iter(keys))
        if key[0] in official_keys and key != official_keys[key[0]]:
            removed += 1
        else:
            filtered.extend(element)
        index = end + 1
    return filtered, removed


def _package(plan_path: Path, include_project_boundary: bool) -> tuple[bytes, dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    source = plan["source_checkpoint"]
    source_path = ROOT / source["gds"]
    if sha256(source_path) != source["sha256"]:
        raise ValueError("submission source differs from the frozen output-tie GDS")
    gate_path = ROOT / source["physical_gate"]
    if sha256(gate_path) != source["physical_gate_sha256"]:
        raise ValueError("submission source physical gate hash differs")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("status") != "pass" or gate.get("gds_sha256") != source["sha256"]:
        raise ValueError("submission source gate is not closed on the source GDS")
    template = plan["template"]
    template_path = ROOT / template["def"]
    if sha256(template_path) != template["sha256"]:
        raise ValueError("TinyTapeout template DEF hash differs")
    width_nm, height_nm, pins = submission_pins(template_path)
    expected_template = (
        template["width_nm"], template["height_nm"], template["total_pins"]
    )
    if (width_nm, height_nm, len(pins)) != expected_template:
        raise ValueError("TinyTapeout template dimensions or pin count differ")
    signal_pins = [pin for pin in pins if pin.use == "SIGNAL"]
    if len(signal_pins) != template["signal_pins"]:
        raise ValueError("TinyTapeout signal-pin count differs")

    source_data = source_path.read_bytes()
    header, structures, endlib = split_library(records(source_data))
    source_top = source["top"]
    submission_top = plan["submission_top"]
    names = [structure_name(item) for item in structures]
    if names.count(source_top) != 1 or submission_top in names:
        raise ValueError("source/submission top-cell naming contract differs")
    parent_references = [
        structure_name(structure)
        for structure in structures
        for record in structure
        if record_type(record) == SNAME and record[4:].rstrip(b"\0").decode("ascii") == source_top
    ]
    if parent_references:
        raise ValueError(f"source top is referenced by {sorted(parent_references)}")

    power_pins = {pin.name: pin for pin in pins if pin.use in {"POWER", "GROUND"}}
    official_power_keys = {
        name: (
            name,
            MET4_DRAW[0],
            MET4_TEXTTYPE,
            ((pin.rect_nm[0] + pin.rect_nm[2]) // 2,
             (pin.rect_nm[1] + pin.rect_nm[3]) // 2),
        )
        for name, pin in power_pins.items()
    }
    source_top_structure = next(item for item in structures if structure_name(item) == source_top)
    filtered_source_top, removed_power_labels = remove_nonofficial_power_labels(
        source_top_structure, official_power_keys
    )
    if removed_power_labels != 2:
        raise ValueError(
            f"expected exactly two redundant internal power labels, removed {removed_power_labels}"
        )
    source_text_keys = existing_text_keys(filtered_source_top)
    rewritten_structures: list[list[bytes]] = []
    changed_names = 0
    added_labels = 0
    for structure in structures:
        if structure_name(structure) != source_top:
            rewritten_structures.append(structure)
            continue
        structure = filtered_source_top
        rewritten: list[bytes] = []
        for record in structure:
            if record_type(record) == STRNAME:
                rewritten.append(ascii_record(STRNAME, submission_top))
                changed_names += 1
            elif record_type(record) == ENDSTR:
                if include_project_boundary:
                    rewritten.extend(rectangle_boundary(PRBOUNDARY, (0, 0, width_nm, height_nm)))
                for pin in signal_pins:
                    rewritten.extend(rectangle_boundary(MET4_DRAW, pin.rect_nm))
                for pin in pins:
                    rewritten.extend(rectangle_boundary(MET4_PIN, pin.rect_nm))
                for pin in pins:
                    lx, by, rx, ty = pin.rect_nm
                    key = (pin.name, MET4_DRAW[0], MET4_TEXTTYPE, ((lx + rx) // 2, (by + ty) // 2))
                    if key not in source_text_keys:
                        rewritten.extend(text_element(pin.name, pin.rect_nm))
                        added_labels += 1
                rewritten.append(record)
            else:
                rewritten.append(record)
        rewritten_structures.append(rewritten)
    if changed_names != 1:
        raise ValueError(f"packaging renamed {changed_names} structures")
    output = b"".join(header)
    output += b"".join(record for structure in rewritten_structures for record in structure)
    output += endlib
    output_names = [structure_name(item) for item in rewritten_structures]
    if source_top in output_names or output_names.count(submission_top) != 1:
        raise ValueError("submission top rename did not close exactly")

    unused_inputs = set(plan["interface_policy"]["isolated_unused_digital_inputs"])
    unused_analog = set(plan["interface_policy"]["isolated_unused_analog_pins"])
    pin_names = {pin.name for pin in pins}
    if not unused_inputs | unused_analog <= pin_names:
        raise ValueError("unused-pin policy contains a name outside the official template")
    return output, {
        "schema_version": 1,
        "status": "pass",
        "source": source["gds"],
        "source_top": source_top,
        "source_sha256": source["sha256"],
        "source_gate": source["physical_gate"],
        "source_gate_sha256": source["physical_gate_sha256"],
        "submission_top": submission_top,
        "submission_sha256": sha256_bytes(output),
        "structure_count": len(structures),
        "changed_existing_gds_records": changed_names + removed_power_labels,
        "removed_redundant_internal_power_labels": removed_power_labels,
        "added_project_boundary_polygons": int(include_project_boundary),
        "project_boundary_layer": list(PRBOUNDARY),
        "added_signal_drawing_polygons": len(signal_pins),
        "added_pin_purpose_polygons": len(pins),
        "ensured_top_level_interface_labels": len(pins),
        "added_top_level_labels": added_labels,
        "met4_drawing_layer": list(MET4_DRAW),
        "met4_pin_layer": list(MET4_PIN),
        "met4_label_texttype": MET4_TEXTTYPE,
        "template_def": template["def"],
        "template_def_sha256": template["sha256"],
        "template_size_nm": [width_nm, height_nm],
        "used_digital_inputs": plan["interface_policy"]["used_digital_inputs"],
        "used_analog_pins": plan["interface_policy"]["used_analog_pins"],
        "physically_tied_low_digital_outputs": plan["interface_policy"]["physically_tied_low_digital_outputs"],
        "isolated_unused_digital_inputs": sorted(unused_inputs),
        "isolated_unused_analog_pins": sorted(unused_analog),
        "output_bytes": len(output),
    }


def package(plan_path: Path) -> tuple[bytes, dict[str, Any]]:
    """Build the release GDS and bind it to the last extracted electrical view."""

    output, report = _package(plan_path, include_project_boundary=True)
    electrical_view, _ = _package(plan_path, include_project_boundary=False)
    report["magic_extracted_preboundary_sha256"] = sha256_bytes(electrical_view)
    report["project_boundary_is_non_electrical_only_delta"] = True
    return output, report


def package_without_project_boundary(plan_path: Path) -> bytes:
    """Reproduce the exact electrically extracted wrapper before prBoundary."""

    output, _ = _package(plan_path, include_project_boundary=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/submission_packaging_plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "build/v3/submission/tt_um_jjassonn69_beamformer.gds")
    parser.add_argument("--report", type=Path, default=ROOT / "build/v3/submission/gds_packaging.json")
    args = parser.parse_args()
    output, report = package(args.plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
