#!/usr/bin/env python3
"""Replace embedded SKY130 HD structures with pinned foundry GDS masters.

Earlier assembly reused a handful of structures already embedded in the
analog checkpoint.  Those structures had been round-tripped through Magic and
were not byte-identical to the pinned foundry library; 10 nm implant insets at
cell abutments alone create hundreds of official full-deck markers.  This pass
keeps every placement and route record unchanged while restoring each used
standard-cell structure from the vendored, commit-pinned GDS master.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from assemble_control_placement_gds import (
    records,
    split_library,
    structure_name,
    unit_record,
)


ROOT = Path(__file__).resolve().parents[2]
CELL_DIR = ROOT / "third_party/sky130_fd_sc_hd_cells"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(source: bytes, cell_dir: Path = CELL_DIR) -> tuple[bytes, dict[str, object]]:
    stream = records(source)
    header, structures, endlib = split_library(stream)
    source_units = unit_record(stream)
    replacements: dict[str, list[bytes]] = {}
    for path in sorted(cell_dir.glob("sky130_fd_sc_hd__*.gds")):
        master_stream = records(path.read_bytes())
        if unit_record(master_stream) != source_units:
            raise ValueError(f"{path}: GDS units differ from source library")
        _, master_structures, _ = split_library(master_stream)
        named = {
            structure_name(structure): structure for structure in master_structures
        }
        if path.stem not in named:
            raise ValueError(f"{path}: expected structure {path.stem} not found")
        replacements[path.stem] = named[path.stem]

    output_structures: list[list[bytes]] = []
    replaced: list[str] = []
    identical: list[str] = []
    for structure in structures:
        name = structure_name(structure)
        master = replacements.get(name)
        if master is None:
            output_structures.append(structure)
        elif master == structure:
            output_structures.append(structure)
            identical.append(name)
        else:
            output_structures.append(master)
            replaced.append(name)

    output = b"".join(header)
    output += b"".join(
        record for structure in output_structures for record in structure
    )
    output += endlib
    return output, {
        "status": "pass",
        "source_sha256": sha256(source),
        "output_sha256": sha256(output),
        "replaced_cells": replaced,
        "replaced_cell_count": len(replaced),
        "already_identical_cells": identical,
        "structure_count": len(structures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output, report = normalize(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
