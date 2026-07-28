#!/usr/bin/env python3
"""Compose control placement GDS without regenerating foundry macro polygons.

Magic is used for DRC, but its CIF interaction writer attempts to synthesize
contact masks where read-only standard-cell macros abut.  This assembler keeps
every source structure byte-for-byte and adds only legal GDS SREF records to a
renamed copy of the support-routed top cell.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Any, Iterable


BGNSTR = 0x05
STRNAME = 0x06
ENDSTR = 0x07
ENDLIB = 0x04
SREF = 0x0A
SNAME = 0x12
XY = 0x10
ENDEL = 0x11
STRANS = 0x1A
ANGLE = 0x1C

NODATA = 0x00
BITARRAY = 0x01
INT4 = 0x03
REAL8 = 0x05
ASCII = 0x06

TOP = "v2_four_channel_control_placed"
SOURCE_LIBRARY_CELLS = {
    "sky130_fd_sc_hd__and2_1",
    "sky130_fd_sc_hd__buf_4",
    "sky130_fd_sc_hd__inv_1",
    "sky130_fd_sc_hd__mux2_1",
    "sky130_fd_sc_hd__tapvpwrvgnd_1",
}


def records(data: bytes) -> list[bytes]:
    result: list[bytes] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("truncated GDS record header")
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 4 or length % 2 or offset + length > len(data):
            raise ValueError(f"invalid GDS record length {length} at byte {offset}")
        result.append(data[offset:offset + length])
        offset += length
    if not result or result[-1][2] != ENDLIB:
        raise ValueError("GDS stream does not end with ENDLIB")
    return result


def record_type(record: bytes) -> int:
    return record[2]


def ascii_payload(record: bytes) -> str:
    return record[4:].rstrip(b"\0").decode("ascii")


def make_record(kind: int, data_type: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\0"
    return struct.pack(">HBB", len(payload) + 4, kind, data_type) + payload


def ascii_record(kind: int, value: str) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > 32 and kind in (STRNAME, SNAME):
        raise ValueError(f"GDS structure name exceeds 32 bytes: {value}")
    return make_record(kind, ASCII, encoded)


def real8(value: float) -> bytes:
    if value == 0.0:
        return b"\0" * 8
    sign = 0x80 if value < 0 else 0
    value = abs(value)
    exponent = 64
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa == 1 << 56:
        mantissa >>= 4
        exponent += 1
    return bytes([sign | exponent]) + mantissa.to_bytes(7, "big")


def structure_name(structure: Iterable[bytes]) -> str:
    names = [ascii_payload(item) for item in structure if record_type(item) == STRNAME]
    if len(names) != 1:
        raise ValueError(f"structure has {len(names)} STRNAME records")
    return names[0]


def split_library(stream: list[bytes]) -> tuple[list[bytes], list[list[bytes]], bytes]:
    first = next(index for index, item in enumerate(stream) if record_type(item) == BGNSTR)
    header = stream[:first]
    structures: list[list[bytes]] = []
    index = first
    while record_type(stream[index]) == BGNSTR:
        end = index
        while record_type(stream[end]) != ENDSTR:
            end += 1
        structures.append(stream[index:end + 1])
        index = end + 1
    if index != len(stream) - 1 or record_type(stream[index]) != ENDLIB:
        raise ValueError("unexpected records between final structure and ENDLIB")
    return header, structures, stream[index]


def reference(item: dict[str, Any], dbu_per_um: int = 1000) -> list[bytes]:
    x, y = map(float, item["origin_um"])
    x0, y0, x1, y1 = map(float, item["bbox_um"])
    width, height = x1 - x0, y1 - y0
    orientation = item["orientation"]
    reflect = orientation in ("MX", "MY")
    angle = 180.0 if orientation in ("MY", "R180") else 0.0
    if orientation == "MX":
        y += height
    elif orientation == "MY":
        x += width
    elif orientation == "R180":
        x += width
        y += height
    elif orientation != "R0":
        raise ValueError(f"unsupported GDS orientation {orientation}")
    result = [make_record(SREF, NODATA), ascii_record(SNAME, item["cell"])]
    # GDSII ANGLE is an optional SREF transformation record and must follow a
    # STRANS record even when reflection is disabled.  Omitting the zero-valued
    # STRANS for R180 makes Magic print an import error while still returning a
    # misleading zero DRC/feedback count.
    if reflect or angle:
        result.append(make_record(
            STRANS, BITARRAY, struct.pack(">H", 0x8000 if reflect else 0x0000)
        ))
    if angle:
        result.append(make_record(ANGLE, REAL8, real8(angle)))
    result.extend((
        make_record(XY, INT4, struct.pack(">ii", round(x * dbu_per_um), round(y * dbu_per_um))),
        make_record(ENDEL, NODATA),
    ))
    return result


def unit_record(stream: list[bytes]) -> bytes:
    matches = [item for item in stream if record_type(item) == 0x03]
    if len(matches) != 1:
        raise ValueError("GDS library does not have exactly one UNITS record")
    return matches[0]


def assemble(
    source_path: Path,
    source_top: str,
    placement: dict[str, Any],
    cell_dir: Path,
) -> tuple[bytes, dict[str, Any]]:
    source_stream = records(source_path.read_bytes())
    header, source_structures, endlib = split_library(source_stream)
    source_names = {structure_name(item) for item in source_structures}
    if source_top not in source_names:
        raise ValueError(f"source top {source_top} is absent")
    if TOP in source_names and TOP != source_top:
        raise ValueError(f"output top {TOP} already exists in source")

    instances = (
        placement["placements"]
        + placement["well_taps"]
        + placement.get("fillers", [])
    )
    referenced = {item["cell"] for item in instances}
    missing = sorted(referenced - source_names)
    imported: list[list[bytes]] = []
    source_units = unit_record(source_stream)
    for name in missing:
        path = cell_dir / f"{name}.gds"
        stream = records(path.read_bytes())
        if unit_record(stream) != source_units:
            raise ValueError(f"{path}: GDS units differ from source library")
        _, structures, _ = split_library(stream)
        names = {structure_name(item) for item in structures}
        if name not in names:
            raise ValueError(f"{path}: expected structure {name} not found")
        unexpected_refs = {
            ascii_payload(record)
            for structure in structures
            for record in structure
            if record_type(record) == SNAME
        } - source_names - names
        if unexpected_refs:
            raise ValueError(f"{path}: unresolved child structures {sorted(unexpected_refs)}")
        imported.extend(structure for structure in structures if structure_name(structure) == name)

    output_structures: list[list[bytes]] = []
    for structure in source_structures:
        name = structure_name(structure)
        if name != source_top:
            output_structures.append(structure)
            continue
        rewritten: list[bytes] = []
        for record in structure:
            if record_type(record) == STRNAME:
                rewritten.append(ascii_record(STRNAME, TOP))
            elif record_type(record) == ENDSTR:
                for item in instances:
                    rewritten.extend(reference(item))
                rewritten.append(record)
            else:
                rewritten.append(record)
        output_structures.append(rewritten)

    final_names = {structure_name(item) for item in output_structures + imported}
    unresolved = referenced - final_names
    if unresolved:
        raise ValueError(f"unresolved placed cell structures: {sorted(unresolved)}")
    output = b"".join(header)
    output += b"".join(record for structure in output_structures for record in structure)
    output += b"".join(record for structure in imported for record in structure)
    output += endlib
    report = {
        "status": "pass",
        "source_gds": str(source_path),
        "source_top": source_top,
        "output_top": TOP,
        "source_structure_count": len(source_structures),
        "imported_structure_count": len(imported),
        "output_structure_count": len(output_structures) + len(imported),
        "sref_count_added": len(instances),
        "orientation_counts": {
            orientation: sum(item["orientation"] == orientation for item in instances)
            for orientation in ("R0", "MX", "MY", "R180")
        },
        "imported_cells": missing,
        "source_cells_reused": sorted(referenced & source_names),
        "output_bytes": len(output),
    }
    return output, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_gds", type=Path)
    parser.add_argument("source_top")
    parser.add_argument("placement", type=Path)
    parser.add_argument("cell_dir", type=Path)
    parser.add_argument("output_gds", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output, report = assemble(
        args.source_gds,
        args.source_top,
        json.loads(args.placement.read_text(encoding="utf-8")),
        args.cell_dir,
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
