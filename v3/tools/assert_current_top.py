#!/usr/bin/env python3
"""Reject any future V3 top-level source that is not the exact frozen checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_top(path: Path | None = None) -> dict[str, str]:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))["current_top_level"]
    selected = (ROOT / current["gds"] if path is None else path).resolve()
    if not selected.is_file():
        raise RuntimeError(f"current V3 top-level GDS does not exist: {selected}")
    observed = sha256(selected)
    if observed != current["gds_sha256"]:
        raise RuntimeError(
            f"refusing non-current V3 top-level GDS: {selected}\n"
            f"expected {current['gds_sha256']}\nobserved {observed}"
        )
    return {
        "status": "pass",
        "gds": str(selected),
        "top_cell": current["top_cell"],
        "sha256": observed,
    }


def main() -> None:
    current = json.loads(CURRENT.read_text(encoding="utf-8"))["current_top_level"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", nargs="?", type=Path, default=ROOT / current["gds"])
    args = parser.parse_args()
    try:
        report = validate_top(args.gds)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
