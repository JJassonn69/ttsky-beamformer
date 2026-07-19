#!/usr/bin/env python3
"""Parse ideal ngspice measurements and enforce the architecture checks."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path


MEASUREMENT_RE = re.compile(
    r"^\s*(sum_rms|diff_rms|error_rms)\s*=\s*([0-9.eE+\-]+)",
    re.MULTILINE,
)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} NGSPICE_LOG", file=sys.stderr)
        return 2

    log_path = Path(sys.argv[1])
    measurements = {
        name: float(value) for name, value in MEASUREMENT_RE.findall(log_path.read_text())
    }
    missing = {"sum_rms", "diff_rms", "error_rms"} - measurements.keys()
    if missing:
        print(f"missing ngspice measurements: {sorted(missing)}", file=sys.stderr)
        return 1

    sum_rms = measurements["sum_rms"]
    diff_rms = measurements["diff_rms"]
    error_rms = measurements["error_rms"]
    if sum_rms <= 1.0e-3:
        print(f"constructive output is unexpectedly small: {sum_rms:g} V RMS")
        return 1
    if diff_rms > sum_rms * 1.0e-6:
        print(f"ideal cancellation failed: residual ratio={diff_rms / sum_rms:g}")
        return 1

    mismatch_null_db = -20.0 * math.log10(error_rms / sum_rms)
    if not 20.0 <= mismatch_null_db <= 22.0:
        print(
            "1 dB / 8 degree mismatch null is outside the expected 20..22 dB "
            f"range: {mismatch_null_db:.3f} dB"
        )
        return 1

    report = {
        **measurements,
        "ideal_cancellation_ratio": diff_rms / sum_rms,
        "mismatch_null_db_1db_8deg": mismatch_null_db,
        "status": "PASS",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
