#!/usr/bin/env python3
"""Prove final routing adds no markers to the full independent KLayout deck."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


POINT_RE = re.compile(r"(?:\(|;)(-?[0-9.]+),(-?[0-9.]+)")


def _canonical_cycle(points: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    rotations: list[tuple[tuple[float, float], ...]] = []
    for sequence in (points, list(reversed(points))):
        rotations.extend(
            tuple(sequence[index:] + sequence[:index])
            for index in range(len(sequence))
        )
    return min(rotations) if rotations else ()


def canonical_value(value: str) -> tuple[Any, ...]:
    points = [(float(x), float(y)) for x, y in POINT_RE.findall(value)]
    if value.startswith("edge-pair:") and len(points) == 4:
        edges = [tuple(sorted(points[:2])), tuple(sorted(points[2:]))]
        return ("edge-pair", *sorted(edges))
    if value.startswith("polygon:"):
        return ("polygon", *_canonical_cycle(points))
    return (value,)


def markers(path: Path) -> Counter[tuple[Any, ...]]:
    root = ET.parse(path).getroot()
    result: Counter[tuple[Any, ...]] = Counter()
    items = root.find("items")
    if items is None:
        raise ValueError(f"{path}: missing KLayout report items")
    for item in items.findall("item"):
        category = (item.findtext("category") or "").strip("'\"")
        values = item.find("values")
        canonical = tuple(
            canonical_value(value.text or "")
            for value in ([] if values is None else values.findall("value"))
        )
        result[(category, canonical)] += int(item.findtext("multiplicity") or 1)
    return result


def category_counts(data: Counter[tuple[Any, ...]]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for (category, _values), count in data.items():
        result[category] += count
    return dict(sorted(result.items()))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(
    source: Path, candidate: Path,
    source_gds: Path | None = None, candidate_gds: Path | None = None,
) -> dict[str, Any]:
    source_markers = markers(source)
    candidate_markers = markers(candidate)
    added = candidate_markers - source_markers
    removed = source_markers - candidate_markers
    reports_fresh = (
        source_gds is None or candidate_gds is None
        or (source.stat().st_mtime_ns >= source_gds.stat().st_mtime_ns
            and candidate.stat().st_mtime_ns >= candidate_gds.stat().st_mtime_ns)
    )
    passed = not added and not removed and reports_fresh
    result = {
        "status": "pass" if passed else "fail",
        "policy": "final routing must preserve the exact normalized marker multiset of the frozen routed source",
        "source_report": str(source),
        "candidate_report": str(candidate),
        "source_marker_count": sum(source_markers.values()),
        "candidate_marker_count": sum(candidate_markers.values()),
        "source_category_counts": category_counts(source_markers),
        "candidate_category_counts": category_counts(candidate_markers),
        "added_marker_count": sum(added.values()),
        "removed_marker_count": sum(removed.values()),
        "added_category_counts": category_counts(added),
        "removed_category_counts": category_counts(removed),
        "reports_newer_than_checked_gds": reports_fresh,
    }
    if source_gds is not None and candidate_gds is not None:
        result["source_gds"] = str(source_gds)
        result["candidate_gds"] = str(candidate_gds)
        result["source_gds_sha256"] = sha256(source_gds)
        result["candidate_gds_sha256"] = sha256(candidate_gds)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path,
        default=Path("build/v2/control_routing/direct/current_internal_klayout_full_drc.xml"),
    )
    parser.add_argument(
        "--candidate", type=Path,
        default=Path("build/v2/control_routing/direct/final_klayout_full_drc.xml"),
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/control_routing/direct/final_klayout_delta_audit.json"),
    )
    parser.add_argument(
        "--source-gds", type=Path,
        default=Path(
            "build/v2/control_routing/openroad_internal/direct/"
            "v2_control_internal_routed.gds"
        ),
    )
    parser.add_argument(
        "--candidate-gds", type=Path,
        default=Path(
            "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
        ),
    )
    args = parser.parse_args()
    report = audit(args.source, args.candidate, args.source_gds, args.candidate_gds)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
