#!/usr/bin/env python3
"""Reject any V3 channel input that is not the exact frozen macro."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "v3/CURRENT.json"
BUILD = ROOT / "build/v3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_channel(path: Path | None = None) -> dict[str, str]:
    manifest = json.loads(CURRENT.read_text(encoding="utf-8"))
    default_gds = ROOT / manifest["gds"]
    selected = (default_gds if path is None else path).resolve()
    if not selected.is_file():
        raise RuntimeError(f"V3 channel GDS does not exist: {selected}")
    expected = manifest["gds_sha256"]
    observed = sha256(selected)
    if observed != expected:
        raise RuntimeError(
            f"refusing non-current V3 channel GDS: {selected}\n"
            f"expected {expected}\nobserved {observed}"
        )
    return {
        "status": "pass",
        "gds": str(selected),
        "top_cell": manifest["top_cell"],
        "sha256": observed,
    }


def audit_generated_build_entries() -> list[str]:
    manifest = json.loads(CURRENT.read_text(encoding="utf-8"))
    allowed = set(manifest["active_generated_build_entries"])
    if not BUILD.exists():
        return []
    unexpected = sorted(path.name for path in BUILD.iterdir() if path.name not in allowed)
    if unexpected:
        raise RuntimeError(
            "obsolete or unregistered V3 build entries are present: "
            + ", ".join(unexpected)
        )
    return sorted(path.name for path in BUILD.iterdir())


def main() -> None:
    manifest = json.loads(CURRENT.read_text(encoding="utf-8"))
    default_gds = ROOT / manifest["gds"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", nargs="?", type=Path, default=default_gds)
    parser.add_argument(
        "--audit-build-directory",
        action="store_true",
        help="also reject obsolete or unregistered entries under build/v3",
    )
    args = parser.parse_args()
    try:
        report = validate_channel(args.gds)
        if args.audit_build_directory:
            report["active_generated_build_entries"] = audit_generated_build_entries()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
