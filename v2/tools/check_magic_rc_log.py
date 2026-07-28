#!/usr/bin/env python3
"""Fail on silent Magic distributed-RC extraction errors and missing markers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FATAL_PATTERNS = {
    "gds_import_error": re.compile(
        r"Error while reading cell|Unexpected record type in input|"
        r"Don't know how to read GDS-II|Nothing in \"cifinput\" section",
        re.IGNORECASE,
    ),
    "wrong_technology": re.compile(
        r"Using technology \"minimum\"|technology file .* not found",
        re.IGNORECASE,
    ),
    "node_extraction_error": re.compile(r"Error in extracting node", re.IGNORECASE),
    "missing_driver_device": re.compile(r"Couldn['’]t find device", re.IGNORECASE),
    "missing_drive_point": re.compile(
        r"force label but no drive point|Did not find the net layout at any drivepoint",
        re.IGNORECASE,
    ),
    "tcl_runtime_error": re.compile(
        r"^(?:invalid command name|wrong # args|can['’]t read \"|error in startup script|"
        r"Error parsing )",
        re.IGNORECASE | re.MULTILINE,
    ),
}


def last_integer(text: str, pattern: str) -> int | None:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    return int(matches[-1]) if matches else None


def audit_text(text: str) -> dict[str, object]:
    drc = last_integer(text, r"^SUPPORT_RC_DRC_COUNT=(\d+)\s*$")
    feedback = last_integer(
        text, r"^SUPPORT_RC_EXTRACTION_FEEDBACK_COUNT=(\d+)\s*$"
    )
    total = last_integer(text, r"^Total Nets:\s*(\d+)\s*$")
    extracted = last_integer(text, r"^Nets extracted:\s*(\d+)\b")
    output = last_integer(text, r"^Nets output:\s*(\d+)\b")
    fatal_matches = {
        name: [match.group(0) for match in pattern.finditer(text)]
        for name, pattern in FATAL_PATTERNS.items()
    }
    fatal_matches = {name: matches for name, matches in fatal_matches.items() if matches}
    output_markers = {
        name: bool(re.search(rf"^{name}=\S+\s*$", text, flags=re.MULTILINE))
        for name in ("SUPPORT_BASE_SPICE", "SUPPORT_RC_SPICE", "SUPPORT_RES_EXT")
    }
    checks = {
        "magic_drc_clean": drc == 0,
        "magic_extraction_feedback_clean": feedback == 0,
        "net_statistics_present": all(
            count is not None for count in (total, extracted, output)
        ),
        "distributed_nets_emitted": (
            total is not None
            and extracted is not None
            and output is not None
            and total > 0
            and extracted > 0
            and output == extracted
        ),
        "both_spice_views_completed": text.count("exttospice finished.") >= 2,
        "output_paths_reported": all(output_markers.values()),
        "no_silent_magic_failures": not fatal_matches,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "drc": drc,
            "extraction_feedback": feedback,
            "total_nets": total,
            "nets_extracted": extracted,
            "nets_output": output,
            "exttospice_completions": text.count("exttospice finished."),
        },
        "output_markers": output_markers,
        "fatal_matches": fatal_matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit_text(args.log.read_text(encoding="utf-8", errors="replace"))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    counts = report["counts"]
    print(
        "Magic RC log "
        + ("passed" if report["passed"] else "FAILED")
        + f": DRC={counts['drc']}, feedback={counts['extraction_feedback']}, "
        + f"nets={counts['nets_output']}/{counts['total_nets']}, "
        + f"SPICE completions={counts['exttospice_completions']}"
    )
    if not report["passed"]:
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        for name, matches in report["fatal_matches"].items():
            print(f"{name}: {matches[0]}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
