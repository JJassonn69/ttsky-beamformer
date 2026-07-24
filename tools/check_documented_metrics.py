#!/usr/bin/env python3
"""Reject drift between the active V2 docs and compact evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, fragment: str, document: str) -> None:
    if fragment not in text:
        raise SystemExit(f"stale {document}: missing {fragment!r}")


def main() -> None:
    evidence = json.loads((ROOT / "v2/evidence/latest_validation.json").read_text())
    candidate = evidence["candidate"]["sha256"]
    submission = evidence["submission"]["gds"]["sha256"]
    rc = evidence["functional_validation"]["nominal_distributed_rc_codebook"]

    readme = (ROOT / "README.md").read_text()
    datasheet = (ROOT / "v2/docs/datasheet.md").read_text()
    status = (ROOT / "v2/evidence/latest_validation.md").read_text()
    plan = (ROOT / "docs/presilicon_plan.md").read_text()

    for document, text in (
        ("root README", readme),
        ("V2 datasheet", datasheet),
        ("validation status", status),
        ("pre-silicon plan", plan),
    ):
        require(text, candidate, document)
    require(readme, submission, "root README")
    require(datasheet, f"{rc['minimum_rejection_db']:.2f} dB", "V2 datasheet")
    require(datasheet, f"{rc['constructive_spread_db']:.3f} dB", "V2 datasheet")
    require(status, f"{rc['minimum_rejection_db']:.3f} dB", "validation status")
    require(status, f"{rc['constructive_spread_db']:.3f} dB", "validation status")
    print("V2 documented metrics match compact evidence")


if __name__ == "__main__":
    main()
