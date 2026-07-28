#!/usr/bin/env python3
"""Replace GDS library/structure timestamps with a fixed reproducible value."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


FIXED_TIME = (2026, 7, 26, 0, 0, 0)


def canonicalize(path: Path) -> int:
    data = bytearray(path.read_bytes())
    offset = 0
    changed = 0
    fixed = struct.pack(">12h", *(FIXED_TIME + FIXED_TIME))
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"truncated GDS record at byte {offset}")
        length, record_type, _data_type = struct.unpack_from(">HBB", data, offset)
        if length < 4 or offset + length > len(data):
            raise ValueError(f"invalid GDS record length {length} at byte {offset}")
        if record_type in (0x01, 0x05):  # BGNLIB or BGNSTR
            if length != 28:
                raise ValueError(f"unexpected timestamp record length {length}")
            data[offset + 4 : offset + 28] = fixed
            changed += 1
        offset += length
    if offset != len(data):
        raise ValueError("GDS record stream did not end on a record boundary")
    path.write_bytes(data)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    args = parser.parse_args()
    count = canonicalize(args.gds)
    print(f"canonicalized {count} GDS timestamp records in {args.gds}")


if __name__ == "__main__":
    main()
