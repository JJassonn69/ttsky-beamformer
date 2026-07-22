#!/usr/bin/env python3
"""Attach a routes-only GDS overlay without rewriting foundry cell geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from assemble_control_placement_gds import (
    ENDSTR,
    STRNAME,
    ascii_record,
    record_type,
    records,
    split_library,
    structure_name,
    unit_record,
)
from assemble_control_power_gds import STRING, origin_reference, text_elements


def assemble(
    source_path: Path,
    source_top: str,
    overlay_path: Path,
    overlay_top: str,
    output_top: str,
    expected_labels: set[str],
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
        raise ValueError("source and route-overlay GDS units differ")

    overlay_structure = next(
        item for item in overlay_structures if structure_name(item) == overlay_top
    )
    labels = text_elements(overlay_structure)
    label_names = {
        next(
            (record[4:].rstrip(b"\0").decode("ascii") for record in element
             if record_type(record) == STRING),
            "",
        )
        for element in labels
    }
    if label_names != expected_labels:
        raise ValueError(
            f"overlay labels {sorted(label_names)} != expected {sorted(expected_labels)}"
        )

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
                for element in labels:
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
    return output, {
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
        "top_level_labels_promoted": sorted(label_names),
        "output_bytes": len(output),
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_gds", type=Path)
    parser.add_argument("source_top")
    parser.add_argument("overlay_gds", type=Path)
    parser.add_argument("overlay_top")
    parser.add_argument("output_top")
    parser.add_argument("output_gds", type=Path)
    parser.add_argument("--expected-label", action="append", default=[])
    parser.add_argument("--expected-labels-from-geometry", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    expected_labels = set(args.expected_label)
    if args.expected_labels_from_geometry:
        geometry = json.loads(
            args.expected_labels_from_geometry.read_text(encoding="utf-8")
        )
        expected_labels.update(
            item.get("gds_label", item["net"]) for item in geometry["routes"]
        )
    output, report = assemble(
        args.source_gds, args.source_top, args.overlay_gds, args.overlay_top,
        args.output_top, expected_labels,
    )
    args.output_gds.parent.mkdir(parents=True, exist_ok=True)
    args.output_gds.write_bytes(output)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
