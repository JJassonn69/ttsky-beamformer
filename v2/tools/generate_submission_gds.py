#!/usr/bin/env python3
"""Generate the repaired, reproducible Tiny Tapeout V2 submission GDS.

The reviewed routed checkpoint stays immutable and hash-locked.  A deterministic
repair stage applies the official-deck geometry corrections, after which this
packager renames the top and adds the exact 53 ``met4.pin`` purpose polygons
required by the pinned Tiny Tapeout 2x2 template and generated LEF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from assemble_control_placement_gds import (
    SNAME,
    STRNAME,
    ENDSTR,
    ENDEL,
    INT4,
    NODATA,
    XY,
    ascii_payload,
    ascii_record,
    make_record,
    record_type,
    records,
    split_library,
    structure_name,
)
from template_pins import submission_pins
from repair_official_precheck_gds import repair


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
OUTPUT = ROOT / "gds/tt_um_jjassonn69_beamformer.gds"
REPORT = ROOT / "build/v2/submission/gds_packaging.json"
TEMPLATE_DEF = ROOT / "build/v2/tt_analog_2x2.def"
LANDING_PLAN = ROOT / "v2/layout/official_precheck_landing_plan.json"
RELOCATION_PLAN = ROOT / "v2/layout/official_precheck_relocation_plan.json"
SOURCE_TOP = "v2_control_quadrature_routed"
SUBMISSION_TOP = "tt_um_jjassonn69_beamformer"
BOUNDARY = 0x08
LAYER = 0x0D
DATATYPE = 0x0E
INT2 = 0x02
MET4_PIN = (71, 16)
MET4_DRAW = (71, 20)
SOURCE_SHA256 = json.loads(
    (ROOT / "v2/layout/vcm_varactor_eco.json").read_text(encoding="utf-8")
)["output_checkpoint"]["sha256"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rectangle_boundary(
    layer: tuple[int, int], rect_nm: tuple[int, int, int, int]
) -> list[bytes]:
    lx, by, rx, ty = rect_nm
    points = (lx, by, rx, by, rx, ty, lx, ty, lx, by)
    return [
        make_record(BOUNDARY, NODATA),
        make_record(LAYER, INT2, struct.pack(">h", layer[0])),
        make_record(DATATYPE, INT2, struct.pack(">h", layer[1])),
        make_record(XY, INT4, struct.pack(">10i", *points)),
        make_record(ENDEL, NODATA),
    ]


def load_landing_plan(path: Path) -> dict[tuple[int, int], str]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    return {
        tuple(map(int, key.split(","))): str(value)
        for key, value in plan["m1_landing_orientation_by_center_nm"].items()
    }


def load_relocation_plan(path: Path) -> dict[tuple[int, int], tuple[int, int]]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    return {
        tuple(map(int, key.split(","))): tuple(map(int, value))
        for key, value in plan["via1_relocation_nm_by_center_nm"].items()
    }


def package(
    source_path: Path = SOURCE,
    template_def: Path = TEMPLATE_DEF,
    landing_plan: Path = LANDING_PLAN,
    relocation_plan: Path = RELOCATION_PLAN,
) -> tuple[bytes, dict[str, object]]:
    source = source_path.read_bytes()
    source_hash = sha256(source)
    if source_hash != SOURCE_SHA256:
        raise ValueError(
            f"V2 source hash {source_hash} != frozen candidate {SOURCE_SHA256}"
        )

    repaired, repair_report = repair(
        source_path,
        SOURCE_TOP,
        load_landing_plan(landing_plan),
        load_relocation_plan(relocation_plan),
    )
    repaired_hash = sha256(repaired)

    header, structures, endlib = split_library(records(repaired))
    names = [structure_name(structure) for structure in structures]
    if names.count(SOURCE_TOP) != 1:
        raise ValueError(f"source must contain exactly one {SOURCE_TOP} structure")
    if SUBMISSION_TOP in names:
        raise ValueError(f"source already contains submission top {SUBMISSION_TOP}")

    parent_references = [
        structure_name(structure)
        for structure in structures
        for record in structure
        if record_type(record) == SNAME and ascii_payload(record) == SOURCE_TOP
    ]
    if parent_references:
        raise ValueError(
            f"source top is referenced as a child by {sorted(parent_references)}"
        )

    width_nm, height_nm, pins = submission_pins(template_def)
    if (width_nm, height_nm) != (334880, 225760):
        raise ValueError(
            f"unexpected 2x2 template size {(width_nm, height_nm)} nm"
        )
    if len(pins) != 53:
        raise ValueError(f"submission pin contract has {len(pins)} ports, expected 53")

    rewritten_structures: list[list[bytes]] = []
    changed_records = 0
    for structure in structures:
        if structure_name(structure) != SOURCE_TOP:
            rewritten_structures.append(structure)
            continue
        rewritten: list[bytes] = []
        for record in structure:
            if record_type(record) == STRNAME:
                rewritten.append(ascii_record(STRNAME, SUBMISSION_TOP))
                changed_records += 1
            elif record_type(record) == ENDSTR:
                # The template contract exposes all 51 signal pins even when
                # this project leaves a digital port unused.  Back every pin
                # purpose with a legal M4 drawing rectangle.  Used pins overlap
                # and extend their routed conductor to the die edge; unused
                # pins remain explicit, isolated NC stubs rather than fake
                # internal connections.  The two power drawings already exist
                # as full-height straps in the electrical candidate.
                for pin in pins:
                    if pin.use == "SIGNAL":
                        rewritten.extend(rectangle_boundary(MET4_DRAW, pin.rect_nm))
                for pin in pins:
                    rewritten.extend(rectangle_boundary(MET4_PIN, pin.rect_nm))
                rewritten.append(record)
            else:
                rewritten.append(record)
        rewritten_structures.append(rewritten)

    if changed_records != 1:
        raise ValueError(f"packaging changed {changed_records} STRNAME records")

    output = b"".join(header)
    output += b"".join(
        record for structure in rewritten_structures for record in structure
    )
    output += endlib
    output_names = [structure_name(item) for item in rewritten_structures]
    if SOURCE_TOP in output_names or output_names.count(SUBMISSION_TOP) != 1:
        raise ValueError("submission top rename did not close exactly")

    return output, {
        "status": "pass",
        "source": str(source_path.relative_to(ROOT)),
        "source_top": SOURCE_TOP,
        "source_sha256": source_hash,
        "electrical_repaired_sha256": repaired_hash,
        "official_precheck_repair": repair_report,
        "landing_plan": str(landing_plan.relative_to(ROOT)),
        "landing_plan_sha256": sha256(landing_plan.read_bytes()),
        "relocation_plan": str(relocation_plan.relative_to(ROOT)),
        "relocation_plan_sha256": sha256(relocation_plan.read_bytes()),
        "submission_top": SUBMISSION_TOP,
        "submission_sha256": sha256(output),
        "structure_count": len(structures),
        "changed_existing_gds_records": changed_records,
        "added_pin_polygon_count": len(pins),
        "added_signal_pin_drawing_polygon_count": sum(
            pin.use == "SIGNAL" for pin in pins
        ),
        "added_gds_records": (
            len(pins) + sum(pin.use == "SIGNAL" for pin in pins)
        ) * 5,
        "met4_drawing_layer": list(MET4_DRAW),
        "met4_pin_layer": list(MET4_PIN),
        "template_def": str(template_def.relative_to(ROOT)),
        "output_bytes": len(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    output, report = package(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
