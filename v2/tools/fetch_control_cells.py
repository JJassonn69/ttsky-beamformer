#!/usr/bin/env python3
"""Fetch the minimal pinned SKY130 HD cells needed by the V2 control core."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESTINATION = PROJECT_ROOT / "third_party" / "sky130_fd_sc_hd_cells"
REPOSITORY = "google/skywater-pdk-libs-sky130_fd_sc_hd"
COMMIT = "ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1"

# Git blob hashes come from the immutable repository tree at COMMIT.  Only
# cells used by the deterministic generic-to-SKY130 mapping are vendored,
# plus the one site-wide physical filler required to keep row wells continuous.
ASSETS = {
    "and2b": {
        "gds": "94b4ebdfe08a21b758ce5e7c85bdcf3a98b68be1",
        "lef": "d8f91155772721d1c36dae796c9ff446a2d705bc",
        "spice": "ab073bb564ba51be8b2aa5d4ca2827d3cd5e419a",
    },
    "dfrtp": {
        "gds": "331b4e73e199cdbf969d4d42f6aa04f311d8b526",
        "lef": "d7f751bd10901987a8e14f602c039053eace6a07",
        "spice": "4eea6d5128ddd055cfb8f5c5a3d48bf622f48e43",
    },
    "dfstp": {
        "gds": "7ef414a71e10fa7a9a93e3def5354a07fea79c85",
        "lef": "e9aa118d15b08c01dbe8dbc8b217040b3cffb05d",
        "spice": "1d8538aed310baba76a30256566dcdc5115c4879",
    },
    "fill": {
        "gds": "a5b94c3d929fd6222ec6ab80f77660d6d18209b3",
        "lef": "7e7738d4caeca5819523159cffd07f82632bf324",
    },
    "nand2": {
        "gds": "07b746d4b197afb2780480a82e8770fd48b762a4",
        "lef": "c10a46e19b846d29da733406159999deea2b47ba",
        "spice": "ddd0527f7a5be2ced72a40a38814399c698742d1",
    },
    "nor2": {
        "gds": "b1eafda120effe5f93ee52d7e17b1621d05fde0c",
        "lef": "0bfcbc3600b27c25e8699c83061e0ed7cd590f3a",
        "spice": "e3dcd01085ffc22181cbc9776a431546cffa1abc",
    },
    "or2": {
        "gds": "8e02e075c804042eee0e68dc5bc9fc5665e893aa",
        "lef": "bacde743108c70167086e2629f7ffba448a09b0c",
        "spice": "b67fa18791e0df125433d0caedd4a3d68fc553d1",
    },
    "or2b": {
        "gds": "135fed2c9cef63444c22eea0bb715f8bf04e1bbf",
        "lef": "371c8af9f0e23a8206943440b05a9db458e2248c",
        "spice": "2d241b35709fa88e9839ca0d8ab0ee3f1916e18b",
    },
    "xor2": {
        "gds": "47cf5c2ad4c09a9023a7cd22f9e865af40a4721a",
        "lef": "2b29525c38b96c3e856df4cb146dcbb50fc82188",
        "spice": "f129b54708f119df6b9dd0d047b43f7d26ad7d20",
    },
}


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for cell, formats in ASSETS.items():
        for extension, expected_sha1 in formats.items():
            name = f"sky130_fd_sc_hd__{cell}_1.{extension}"
            destination = DESTINATION / name
            if destination.exists():
                data = destination.read_bytes()
            else:
                url = (
                    f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/"
                    f"cells/{cell}/{name}"
                )
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read()
                destination.write_bytes(data)
            actual_sha1 = git_blob_sha1(data)
            if actual_sha1 != expected_sha1:
                raise SystemExit(
                    f"{destination}: Git blob SHA-1 {actual_sha1} != {expected_sha1}"
                )
            print(f"verified {destination.relative_to(PROJECT_ROOT)} {actual_sha1}")


if __name__ == "__main__":
    main()
