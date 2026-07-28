#!/usr/bin/env python3
"""Run the Tiny Tapeout geometry-only precheck subset on the V3 selector pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PINNED_SUPPORT_COMMIT = "d65690eeb1d4afd26aef795c805a23d9d9daf9d1"
DEFAULT_GDS = ROOT / "build" / "v3" / "selector_route_pilot" / "v3_selector_route_pilot.gds"
DEFAULT_REPORT_DIR = ROOT / "build" / "v3" / "selector_route_pilot"
DEFAULT_TOP = "v3_selector_route_pilot"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker_count(path: Path) -> int:
    return len(ET.parse(path).getroot().findall(".//items/item"))


def resolve_klayout(value: Path | None) -> Path:
    if value:
        return value
    discovered = shutil.which("klayout")
    if discovered:
        return Path(discovered)
    mac = Path("/Applications/KLayout/klayout.app/Contents/MacOS/klayout")
    if mac.is_file():
        return mac
    raise SystemExit("KLayout was not found; pass --klayout")


def run_check(name: str, command: list[str], report: Path, log: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=report.parent, text=True, capture_output=True, check=False)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"{name} KLayout process failed with exit {result.returncode}; see {log}")
    markers = marker_count(report)
    return {
        "process_exit_code": result.returncode,
        "markers": markers,
        "report": str(report.relative_to(ROOT)),
        "report_sha256": sha256(report),
        "log": str(log.relative_to(ROOT)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support-tools", type=Path, required=True)
    parser.add_argument("--klayout", type=Path)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--top", default=DEFAULT_TOP)
    args = parser.parse_args()
    klayout = resolve_klayout(args.klayout)
    args.report_dir = args.report_dir.resolve()
    observed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=args.support_tools, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    if observed_commit != PINNED_SUPPORT_COMMIT:
        raise SystemExit(f"tt-support-tools differs: expected {PINNED_SUPPORT_COMMIT}, got {observed_commit}")
    deck_dir = args.support_tools / "precheck" / "tech-files"
    args.report_dir.mkdir(parents=True, exist_ok=True)
    gds = args.gds.resolve()
    common = [str(klayout), "-b"]
    checks = {
        "feol": (deck_dir / "sky130A_mr.drc", ["feol=true", "thr=1"]),
        "beol": (deck_dir / "sky130A_mr.drc", ["beol=true", "thr=1"]),
        "offgrid": (deck_dir / "sky130A_mr.drc", ["offgrid=true", "thr=1"]),
        "zero_area": (deck_dir / "zeroarea.rb.drc", []),
        "pin_purpose_overlap": (
            deck_dir / "pin_label_purposes_overlapping_drawing.rb.drc",
            ["pin_label_purposes_overlapping_drawing=true", f"top_cell_name={args.top}", "threads=1"],
        ),
    }
    results: dict[str, object] = {}
    for name, (deck, variables) in checks.items():
        report = args.report_dir / f"precheck_{name}.xml"
        log = args.report_dir / f"precheck_{name}.log"
        command = [*common, "-r", str(deck), "-rd", f"input={gds}"]
        for variable in variables:
            command.extend(("-rd", variable))
        command.extend(("-rd", f"report={report}", "-rd", f"report_file={report}"))
        results[name] = run_check(name, command, report, log)

    flat = subprocess.run(
        [
            "python3", str(ROOT / "tools" / "check_gds_flat_rules.py"),
            str(gds), "--top", args.top,
        ], cwd=ROOT, text=True, capture_output=True, check=False,
    )
    flat_log = args.report_dir / "precheck_flat_rules.log"
    flat_log.write_text(flat.stdout + flat.stderr, encoding="utf-8")
    results["project_flat_rules"] = {
        "process_exit_code": flat.returncode,
        "markers": 0 if flat.returncode == 0 else None,
        "log": str(flat_log.relative_to(ROOT)),
    }
    status = "pass" if flat.returncode == 0 and all(item["markers"] == 0 for item in results.values()) else "fail"
    summary = {
        "schema_version": 1,
        "status": status,
        "scope": "pilot-GDS geometry subset; not the full Tiny Tapeout wrapper/interface precheck",
        "gds": str(gds.relative_to(ROOT)),
        "gds_sha256": sha256(gds),
        "top": args.top,
        "support_tools_commit": observed_commit,
        "klayout_binary": str(klayout),
        "klayout_binary_sha256": sha256(klayout),
        "checks": results,
        "deferred_until_integrated_top": [
            "top-module and project-boundary contract",
            "LEF/template pin equivalence and analog-pin adjacency",
            "power-pin and Verilog syntax contract",
            "forbidden/invalid-layer and unique-top checks in the packaged artifact",
            "urpm-to-nwell check and full official GitHub Action",
        ],
    }
    output = args.report_dir / "precheck_summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
