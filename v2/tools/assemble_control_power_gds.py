#!/usr/bin/env python3
"""Attach the verified routes-only power overlay to the exact placed GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from assemble_control_placement_gds import (
    ENDSTR,
    ENDEL,
    INT4,
    NODATA,
    SNAME,
    SREF,
    STRNAME,
    XY,
    ascii_record,
    make_record,
    record_type,
    records,
    split_library,
    structure_name,
    unit_record,
)

import struct


TEXT = 0x0C
STRING = 0x19


def origin_reference(name: str) -> list[bytes]:
    return [
        make_record(SREF, NODATA),
        ascii_record(SNAME, name),
        make_record(XY, INT4, struct.pack(">ii", 0, 0)),
        make_record(ENDEL, NODATA),
    ]


def text_elements(structure: list[bytes]) -> list[list[bytes]]:
    """Return complete raw TEXT elements for top-level label promotion."""

    result: list[list[bytes]] = []
    current: list[bytes] | None = None
    for record in structure:
        kind = record_type(record)
        if kind == TEXT:
            if current is not None:
                raise ValueError("nested GDS text element")
            current = [record]
        elif current is not None:
            current.append(record)
            if kind == ENDEL:
                result.append(current)
                current = None
    if current is not None:
        raise ValueError("unterminated GDS text element")
    return result


def assemble(
    source_path: Path,
    source_top: str,
    overlay_path: Path,
    overlay_top: str,
    output_top: str,
) -> tuple[bytes, dict[str, Any]]:
    source_stream = records(source_path.read_bytes())
    source_header, source_structures, source_endlib = split_library(source_stream)
    source_names = {structure_name(item) for item in source_structures}
    if source_top not in source_names:
        raise ValueError(f"source top {source_top} is absent")
    if output_top in source_names and output_top != source_top:
        raise ValueError(f"output top {output_top} already exists")

    overlay_stream = records(overlay_path.read_bytes())
    _, overlay_structures, _ = split_library(overlay_stream)
    overlay_names = {structure_name(item) for item in overlay_structures}
    if overlay_top not in overlay_names:
        raise ValueError(f"overlay top {overlay_top} is absent")
    collisions = source_names & overlay_names
    if collisions:
        raise ValueError(f"overlay structure collision: {sorted(collisions)}")
    if unit_record(source_stream) != unit_record(overlay_stream):
        raise ValueError("source and power-overlay GDS units differ")
    overlay_top_structure = next(
        item for item in overlay_structures if structure_name(item) == overlay_top
    )
    promoted_labels = text_elements(overlay_top_structure)
    promoted_names = [
        next(
            (record[4:].rstrip(b"\0").decode("ascii") for record in element
             if record_type(record) == STRING),
            "",
        )
        for element in promoted_labels
    ]
    if sorted(promoted_names) != ["VDPWR", "VGND"]:
        raise ValueError(f"unexpected power-overlay labels: {sorted(promoted_names)}")

    output_structures: list[list[bytes]] = []
    for structure in source_structures:
        if structure_name(structure) != source_top:
            output_structures.append(structure)
            continue
        rewritten: list[bytes] = []
        for record in structure:
            if record_type(record) == STRNAME:
                rewritten.append(ascii_record(STRNAME, output_top))
            elif record_type(record) == ENDSTR:
                # GDS labels inside a referenced overlay can lose priority to
                # a device-terminal label during hierarchical extraction.
                # Promote the same raw labels to the assembled top so VDPWR
                # and VGND are unambiguous external ports in LVS.
                for element in promoted_labels:
                    rewritten.extend(element)
                rewritten.extend(origin_reference(overlay_top))
                rewritten.append(record)
            else:
                rewritten.append(record)
        output_structures.append(rewritten)

    output = b"".join(source_header)
    output += b"".join(record for structure in output_structures for record in structure)
    output += b"".join(record for structure in overlay_structures for record in structure)
    output += source_endlib
    report = {
        "status": "pass",
        "source_gds": str(source_path),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_top": source_top,
        "overlay_gds": str(overlay_path),
        "overlay_sha256": hashlib.sha256(overlay_path.read_bytes()).hexdigest(),
        "overlay_top": overlay_top,
        "output_top": output_top,
        "source_structure_count": len(source_structures),
        "overlay_structure_count": len(overlay_structures),
        "output_structure_count": len(output_structures) + len(overlay_structures),
        "overlay_reference_count_added": 1,
        "top_level_power_labels_promoted": sorted(promoted_names),
        "output_bytes": len(output),
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_gds", type=Path)
    parser.add_argument("source_top")
    parser.add_argument("overlay_gds", type=Path)
    parser.add_argument("overlay_top")
    parser.add_argument("output_top")
    parser.add_argument("output_gds", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output, report = assemble(
        args.source_gds, args.source_top, args.overlay_gds, args.overlay_top,
        args.output_top,
    )
    args.output_gds.parent.mkdir(parents=True, exist_ok=True)
    args.output_gds.write_bytes(output)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
