#!/usr/bin/env python3
"""Generate the matrix plus the reserved balanced output collector."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_matrix_pilot as matrix_gen
import generate_channel_row_pilot as row_gen
import generate_vector_unit_pilot as unit_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "v3/layout/channel_matrix_placement.json"
UNIT = ROOT / "v3/layout/vector_unit_placement.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
COLLECTION = ROOT / "v3/layout/channel_output_collection.json"
DEFAULT_OUTPUT = ROOT / "build/v3/channel_output_collection_pilot/build.tcl"
TOP = "v3_channel_output_collection_pilot"


def build_tcl(
    matrix: dict[str, Any], unit: dict[str, Any], catalog: dict[str, Any],
    collection: dict[str, Any],
) -> str:
    source = matrix_gen.build_tcl(matrix, unit, catalog)
    source = source.replace("channel_matrix_pilot", "channel_output_collection_pilot")
    source = source.replace("v3_channel_matrix_pilot", TOP)
    source = source.replace("V3_CHANNEL_MATRIX", "V3_CHANNEL_OUTPUT_COLLECTION")
    source = source.replace("channel-matrix pilot", "channel-output-collection pilot")

    # Unit output aliases are removed before the common buses intentionally
    # join all fifteen drains.  The final roots receive the only output names.
    output_label = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_out[pn] center metal3\n"
        r"port make\nport class output\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = output_label.subn("", source)
    if removed != 30:
        raise RuntimeError(f"expected to remove 30 unit output aliases, removed {removed}")

    commands = [row_gen.local_route(item) for item in collection["segments"]]
    for at in collection["via2_points"]:
        commands.extend(unit_gen.via2_stack(*unit_gen.shifted(at)))
    labels = [
        matrix_gen.label(
            f"channel_out{polarity}", value["root"], value["root_layer"], output=True
        )
        for polarity, value in collection["spines"].items()
    ]
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("matrix template save marker changed")
    return source.replace(marker, f"\n{'\n'.join(commands + labels)}{marker}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--collection", type=Path, default=COLLECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.unit, args.catalog, args.collection,
    )]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_tcl(*values), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
