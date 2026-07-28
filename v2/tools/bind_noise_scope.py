#!/usr/bin/env python3
"""Bind the documented switched-noise residual to the frozen V2 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "v2/layout/vcm_varactor_eco.json"
EXTRACTION = ROOT / "build/v2/control_routing/final_rc/coverage_audit.json"
SCOPE = ROOT / "v2/evidence/noise_scope.json"


def bind(scope: dict, contract: dict, extraction: dict) -> dict:
    if scope.get("status") != "deferred_requires_periodic_noise_or_measurement":
        raise ValueError("noise residual classification changed")
    if extraction.get("status") != "pass":
        raise ValueError("distributed-RC extraction is not passing")
    result = dict(scope)
    result.update({
        "candidate_gds_sha256": contract["output_checkpoint"]["sha256"],
        "base_netlist_sha256": extraction["sha256"]["base"],
        "distributed_rc_netlist_sha256": extraction["sha256"]["distributed_rc"],
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, default=SCOPE)
    args = parser.parse_args()
    result = bind(
        json.loads(args.scope.read_text(encoding="utf-8")),
        json.loads(CONTRACT.read_text(encoding="utf-8")),
        json.loads(EXTRACTION.read_text(encoding="utf-8")),
    )
    args.scope.write_text(
        json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        key: result[key] for key in (
            "status", "candidate_gds_sha256", "base_netlist_sha256",
            "distributed_rc_netlist_sha256",
        )
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
