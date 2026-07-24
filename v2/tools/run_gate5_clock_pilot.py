#!/usr/bin/env python3
"""Run bounded master-clock duty-cycle and deterministic-jitter stresses."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "v2/tools/run_control_postlayout_smoke.py"
CONTRACT = ROOT / "v2/layout/vcm_varactor_eco.json"
EXTRACTION = ROOT / "build/v2/control_routing/final_rc/coverage_audit.json"
BASELINE = ROOT / "build/v2/postlayout_smoke/base/codebook/selected_0_incident_0_startup_op_step_5ns/report.json"
REPORT = ROOT / "build/v2/signoff/gate5_clock_pilot.json"


def cases(timeout: int) -> dict[str, list[str]]:
    common = [
        "python3", str(SMOKE), "--view", "base", "--beam", "0",
        "--incident-beam", "0", "--startup", "op",
        "--analysis-start-us", "2", "--analysis-stop-us", "4",
        "--transient-step-ns", "5", "--timeout", str(timeout),
    ]
    return {
        "duty_40pct": common + ["--clock-duty-percent", "40"],
        "duty_60pct": common + ["--clock-duty-percent", "60"],
        "jitter_500ps": common + ["--clock-jitter-ps", "500"],
        "jitter_1000ps": common + ["--clock-jitter-ps", "1000"],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_from_stdout(stdout: str) -> Path | None:
    values = [
        Path(line.split("=", 1)[1].strip())
        for line in stdout.splitlines() if line.startswith("report=")
    ]
    if not values:
        return None
    return values[-1] if values[-1].is_absolute() else ROOT / values[-1]


def run_case(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    path = report_from_stdout(completed.stdout)
    report = json.loads(path.read_text()) if path and path.is_file() else None
    return {
        "name": name,
        "returncode": completed.returncode,
        "report": str(path.relative_to(ROOT)) if path else None,
        "result": report,
        "stdout_tail": completed.stdout.splitlines()[-10:],
        "stderr_tail": completed.stderr.splitlines()[-10:],
    }


def gain_db(report: dict[str, Any]) -> float:
    return 20.0 * math.log10(
        float(report["analysis"]["output_tone_rms_v"]) / float(report["input_peak_v"])
    )


def evaluate(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text())
    extraction = json.loads(EXTRACTION.read_text())
    baseline = json.loads(BASELINE.read_text())
    frozen_hash = contract["output_checkpoint"]["sha256"]
    base_hash = extraction["sha256"]["base"]
    errors: list[str] = []
    warnings: list[str] = []
    if baseline.get("status") != "pass":
        errors.append("nominal Gate-4 baseline is not passing")
    if baseline.get("gds_sha256") != frozen_hash or baseline.get("netlist_sha256") != base_hash:
        errors.append("nominal Gate-4 baseline is stale")
    for name, item in sorted(results.items()):
        report = item.get("result")
        if item.get("returncode") or not isinstance(report, dict):
            errors.append(f"{name}: simulation did not produce a report")
            continue
        if report.get("status") != "pass":
            errors.append(f"{name}: simulation failed: {report.get('errors')}")
        if report.get("gds_sha256") != frozen_hash or report.get("netlist_sha256") != base_hash:
            errors.append(f"{name}: report is bound to stale physical artifacts")

    metrics: dict[str, Any] = {}
    if not errors:
        nominal_gain = gain_db(baseline)
        gain_delta = {
            name: gain_db(item["result"]) - nominal_gain
            for name, item in sorted(results.items())
        }
        common_mode = {
            name: item["result"]["analysis"]["output_common_mode_v"]
            for name, item in sorted(results.items())
        }
        period_error_ppm = {
            name: max(
                abs(float(phase["period_s"]) / 250e-9 - 1.0) * 1e6
                for phase in item["result"]["analysis"]["phases"]
            )
            for name, item in sorted(results.items())
        }
        metrics = {
            "nominal_gain_db": nominal_gain,
            "gain_delta_db": gain_delta,
            "output_common_mode_v": common_mode,
            "maximum_quadrature_period_error_ppm": period_error_ppm,
        }
        for name, delta in gain_delta.items():
            if abs(delta) > 3.0:
                errors.append(f"{name}: conversion gain changes by {delta:.3f} dB")
            elif abs(delta) > 1.0:
                warnings.append(f"{name}: conversion gain changes by {delta:.3f} dB")
        for name, value in common_mode.items():
            if value < 0.8:
                errors.append(f"{name}: output common mode is below 0.8 V")

    return {
        "schema_version": 1,
        "gate": 5,
        "scope": "bounded base-extracted master-clock duty/jitter sensitivity pilot",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "frozen_gds_sha256": frozen_hash,
        "base_netlist_sha256": base_hash,
        "baseline_report": str(BASELINE.relative_to(ROOT)),
        "baseline_report_sha256": sha256(BASELINE),
        "case_count": len(results),
        "metrics": metrics,
        "cases": {
            name: {
                "report": item.get("report"),
                "report_sha256": (
                    sha256(ROOT / item["report"])
                    if item.get("report") and (ROOT / item["report"]).is_file() else None
                ),
                "status": item.get("result", {}).get("status", "missing")
                if isinstance(item.get("result"), dict) else "missing",
            }
            for name, item in sorted(results.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        raise SystemExit("jobs must be between one and four")
    work = cases(args.timeout)
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_case, name, command): name
            for name, command in work.items()
        }
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            results[item["name"]] = item
            status = item.get("result", {}).get("status") if item.get("result") else "missing"
            print(f"{item['name']}: {status}", flush=True)
    report = evaluate(results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
