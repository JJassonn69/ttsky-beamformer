#!/usr/bin/env python3
"""Package the frozen V2 layout under the Tiny Tapeout submission top name.

The physical V2 candidate already contains the authenticated 2x2 template
boundary and all signal/power pin geometry.  Submission packaging therefore
changes exactly one GDS record: the top structure name.  Every other record is
preserved byte-for-byte and the source hash is frozen here so an arbitrary
intermediate layout cannot be promoted accidentally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from assemble_control_placement_gds import (
    SNAME,
    STRNAME,
    ascii_payload,
    ascii_record,
    record_type,
    records,
    split_library,
    structure_name,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
OUTPUT = ROOT / "gds/tt_um_jjassonn69_beamformer.gds"
REPORT = ROOT / "build/v2/submission/gds_packaging.json"
SOURCE_TOP = "v2_control_quadrature_routed"
SUBMISSION_TOP = "tt_um_jjassonn69_beamformer"
SOURCE_SHA256 = "90b51a5f37fd114a8cb24afec32ba1c5364b64f15865f19fe738caa7cb8a994a"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(source: bytes) -> tuple[bytes, dict[str, object]]:
    source_hash = sha256(source)
    if source_hash != SOURCE_SHA256:
        raise ValueError(
            f"V2 source hash {source_hash} != frozen candidate {SOURCE_SHA256}"
        )

    header, structures, endlib = split_library(records(source))
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
        "source": str(SOURCE.relative_to(ROOT)),
        "source_top": SOURCE_TOP,
        "source_sha256": source_hash,
        "submission_top": SUBMISSION_TOP,
        "submission_sha256": sha256(output),
        "structure_count": len(structures),
        "changed_gds_records": changed_records,
        "geometry_records_changed": 0,
        "output_bytes": len(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    output, report = package(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
