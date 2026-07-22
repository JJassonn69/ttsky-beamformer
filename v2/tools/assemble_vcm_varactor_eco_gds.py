#!/usr/bin/env python3
"""Append only the VCM-varactor ECO to the hash-frozen user-routed GDS."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from assemble_control_placement_gds import (
    ENDSTR,
    SNAME,
    SREF,
    STRNAME,
    record_type,
    records,
    split_library,
    structure_name,
)


SOURCE_TOP = "v2_control_quadrature_routed"
OVERLAY_TOP = "v2_vcm_varactor_eco_overlay"
VARACTOR_CELL = "sky130_fd_pr__cap_var_lvt_88578Y"
SOURCE_SHA256 = "d9c9aae5771af815833668374924baee23f60a51747c7966e2517dcb6f6a6130"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sref_targets(structure: list[bytes]) -> list[str]:
    result: list[str] = []
    inside = False
    for record in structure:
        kind = record_type(record)
        if kind == SREF:
            inside = True
        elif inside and kind == SNAME:
            result.append(record[4:].rstrip(b"\0").decode("ascii"))
            inside = False
    return result


def assemble(source: bytes, overlay: bytes) -> tuple[bytes, dict[str, Any]]:
    source_hash = sha256(source)
    if source_hash != SOURCE_SHA256:
        raise ValueError(
            f"ECO source hash {source_hash} != user-routed source {SOURCE_SHA256}"
        )
    source_header, source_structures, source_endlib = split_library(records(source))
    source_names = {structure_name(item) for item in source_structures}
    if SOURCE_TOP not in source_names:
        raise ValueError(f"source top {SOURCE_TOP} is absent")
    if VARACTOR_CELL in source_names:
        raise ValueError("source already contains the varactor PCell")

    _, overlay_structures, _ = split_library(records(overlay))
    overlay_by_name = {
        structure_name(item): item for item in overlay_structures
    }
    if OVERLAY_TOP not in overlay_by_name:
        raise ValueError(f"overlay top {OVERLAY_TOP} is absent")
    overlay_top = overlay_by_name[OVERLAY_TOP]
    targets = sref_targets(overlay_top)
    if targets != [VARACTOR_CELL] * 4:
        raise ValueError(f"overlay varactor references changed: {targets}")
    imported = [
        structure for structure in overlay_structures
        if structure_name(structure) != OVERLAY_TOP
    ]
    imported_names = {structure_name(item) for item in imported}
    if imported_names != {VARACTOR_CELL}:
        raise ValueError(f"unexpected ECO child structures: {sorted(imported_names)}")
    collisions = source_names & imported_names
    if collisions:
        raise ValueError(f"ECO structure collision: {sorted(collisions)}")

    strname_index = next(
        index for index, record in enumerate(overlay_top)
        if record_type(record) == STRNAME
    )
    end_index = next(
        index for index, record in enumerate(overlay_top)
        if record_type(record) == ENDSTR
    )
    eco_elements = overlay_top[strname_index + 1:end_index]
    if not eco_elements:
        raise ValueError("ECO overlay contains no elements")

    rewritten: list[list[bytes]] = []
    for structure in source_structures:
        if structure_name(structure) != SOURCE_TOP:
            rewritten.append(structure)
            continue
        top: list[bytes] = []
        for record in structure:
            if record_type(record) == ENDSTR:
                top.extend(eco_elements)
            top.append(record)
        rewritten.append(top)

    output = b"".join(source_header)
    output += b"".join(record for structure in rewritten for record in structure)
    output += b"".join(record for structure in imported for record in structure)
    output += source_endlib
    return output, {
        "status": "pass",
        "source_sha256": source_hash,
        "source_top": SOURCE_TOP,
        "source_preserves_user_trim_routes": True,
        "overlay_sha256": sha256(overlay),
        "overlay_top": OVERLAY_TOP,
        "varactor_cell": VARACTOR_CELL,
        "varactor_reference_count_added": len(targets),
        "imported_structure_count": len(imported),
        "output_sha256": sha256(output),
        "output_top": SOURCE_TOP,
        "output_bytes": len(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output, report = assemble(args.source.read_bytes(), args.overlay.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
