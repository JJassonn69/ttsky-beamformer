#!/usr/bin/env python3
"""Rebind verified path-dependent mismatch evidence to a semantic bundle ID.

Older pilot manifests hashed generated include paths, so otherwise identical
model bundles built in different work directories received different IDs. This
tool verifies each legacy manifest and every referenced file before replacing
only that legacy ID in the frozen transform/report JSON. Electrical results are
never edited.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from run_gate5_mismatch_pilot import (
    ROOT,
    build_model_bundle,
    canonical_sha256,
    model_bundle_semantic_identity,
    sha256,
)


DEFAULT_BUILD = Path("build/v2/gate5_mismatch_pilot")
DEFAULT_LEGACY_MANIFESTS = (
    Path("build/v2/gate5_mismatch_remote_stage/models/manifest.json"),
    Path("build/v2/gate5_mismatch_pilot_mac_low/models/manifest.json"),
    Path("build/v2/gate5_mismatch_pilot_mac/models/manifest.json"),
)


def root_path(path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def verify_file(path: Path | str, expected_hash: str, label: str) -> None:
    resolved = root_path(path)
    if not resolved.is_file():
        raise ValueError(f"{label}: missing file {path}")
    actual = sha256(resolved)
    if actual != expected_hash:
        raise ValueError(f"{label}: hash differs for {path}")


def verify_legacy_manifest(path: Path) -> dict[str, Any]:
    resolved = root_path(path)
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{path}: expected a legacy schema-1 manifest")
    legacy_hash = manifest.get("bundle_sha256")
    payload = copy.deepcopy(manifest)
    payload.pop("bundle_sha256", None)
    if canonical_sha256(payload) != legacy_hash:
        raise ValueError(f"{path}: legacy manifest hash differs")
    verify_file(manifest["include"], manifest["include_sha256"], f"{path} include")
    for model, item in manifest.get("files", {}).items():
        for field in (
            "source_pm3", "source_corner", "mismatch_coefficients",
            "patched_pm3", "patched_corner",
        ):
            verify_file(
                item[field], item[f"{field}_sha256"], f"{path} {model} {field}"
            )
    return {
        "path": str(path),
        "sha256": sha256(resolved),
        "legacy_bundle_sha256": legacy_hash,
        "status": "verified",
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument(
        "--legacy-manifest", type=Path, action="append",
        dest="legacy_manifests",
        help="legacy schema-1 manifest to verify; may be supplied more than once",
    )
    args = parser.parse_args()
    build = root_path(args.build)
    legacy_paths = tuple(args.legacy_manifests or DEFAULT_LEGACY_MANIFESTS)
    verified = [verify_legacy_manifest(path) for path in legacy_paths]
    semantic_identity = model_bundle_semantic_identity()
    semantic_hash = canonical_sha256(semantic_identity)
    mapping = {
        item["legacy_bundle_sha256"]: semantic_hash for item in verified
    }
    if len(mapping) != len(verified):
        raise SystemExit("legacy manifest list contains duplicate bundle identities")

    _include, current = build_model_bundle(build)
    if current.get("bundle_sha256") != semantic_hash:
        raise SystemExit("new path-independent bundle identity is inconsistent")

    records: list[dict[str, Any]] = []
    for seed_dir in sorted(build.glob("seed_[0-9][0-9][0-9][0-9]")):
        transform_path = seed_dir / "transform.json"
        if not transform_path.is_file():
            continue
        transform = json.loads(transform_path.read_text(encoding="utf-8"))
        old = transform.get("model_bundle_sha256")
        if old == semantic_hash:
            legacy = semantic_hash
        elif old in mapping:
            legacy = old
            transform["model_bundle_sha256"] = semantic_hash
            write_json(transform_path, transform)
        else:
            raise SystemExit(f"{seed_dir.name}: unverified model bundle identity {old}")
        case_records: dict[str, Any] = {}
        for name in ("constructive", "null", "background"):
            report_path = seed_dir / name / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report_old = report.get("model_bundle_sha256")
            if report_old not in (legacy, semantic_hash):
                raise SystemExit(
                    f"{seed_dir.name} {name}: report bundle differs from transform"
                )
            if report.get("status") != "pass" or report.get("timed_out"):
                raise SystemExit(f"{seed_dir.name} {name}: report is not passing")
            before = sha256(report_path)
            if report_old != semantic_hash:
                report["model_bundle_sha256"] = semantic_hash
                write_json(report_path, report)
            case_records[name] = {
                "original_report_sha256": before,
                "rebound_report_sha256": sha256(report_path),
            }
        records.append({
            "seed": int(seed_dir.name.removeprefix("seed_")),
            "legacy_bundle_sha256": legacy,
            "semantic_bundle_sha256": semantic_hash,
            "transform_sha256": sha256(transform_path),
            "cases": case_records,
        })

    if len(records) != 60:
        raise SystemExit(f"expected 60 complete seed directories, found {len(records)}")
    audit = {
        "schema_version": 1,
        "status": "pass",
        "scope": "metadata-only migration from path-dependent to semantic model-bundle identity",
        "semantic_bundle_sha256": semantic_hash,
        "semantic_identity": semantic_identity,
        "verified_legacy_manifests": verified,
        "seed_count": len(records),
        "seeds": records,
    }
    audit_path = build / "bundle_rebinding_audit.json"
    write_json(audit_path, audit)
    print(f"status=pass seeds={len(records)} semantic_bundle_sha256={semantic_hash}")
    print(f"report={audit_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
