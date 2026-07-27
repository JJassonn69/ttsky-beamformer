#!/usr/bin/env python3
"""Reject any V3 channel input that is not the exact frozen macro."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(CURRENT.read_text(encoding="utf-8"))
    default_gds = ROOT / manifest["gds"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", nargs="?", type=Path, default=default_gds)
    args = parser.parse_args()
    path = args.gds.resolve()
    expected = manifest["gds_sha256"]
    observed = sha256(path)
    if observed != expected:
        raise SystemExit(
            f"refusing non-current V3 channel GDS: {path}\n"
            f"expected {expected}\nobserved {observed}"
        )
    print(json.dumps({
        "status": "pass",
        "gds": str(path),
        "top_cell": manifest["top_cell"],
        "sha256": observed,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
