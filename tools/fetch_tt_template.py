#!/usr/bin/env python3
"""Legacy V1 helper: fetch the historical Tiny Tapeout 1x2 DEF."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import urlopen

COMMIT = "d65690eeb1d4afd26aef795c805a23d9d9daf9d1"
SHA256 = "042803101760925474f602e69119f497922eb912c37a6651bed030164bb576af"
URL = (
    "https://raw.githubusercontent.com/TinyTapeout/tt-support-tools/"
    f"{COMMIT}/tech/sky130A/def/analog/tt_analog_1x2.def"
)
OUTPUT = Path("build/layout/tt_analog_1x2.def")


def main() -> None:
    data = urlopen(URL, timeout=30).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"DEF SHA-256 mismatch: expected {SHA256}, got {digest}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(data)
    print(f"Authenticated {OUTPUT}: sha256={digest}")


if __name__ == "__main__":
    main()
