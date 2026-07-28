#!/usr/bin/env python3
"""Run a bounded Gate-5 base-extracted RF, amplitude, and load pilot."""

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
REPORT = ROOT / "build/v2/signoff/gate5_sensitivity_pilot.json"


def cases(timeout: int) -> dict[str, list[str]]:
    common = [
        "python3", str(SMOKE), "--view", "base", "--beam", "0",
        "--incident-beam", "0", "--startup", "op",
        "--analysis-start-us", "2", "--analysis-stop-us", "4",
        "--transient-step-ns", "5", "--timeout", str(timeout),
    ]
    return {
        "rf_4p5mhz": common + ["--input-frequency-mhz", "4.5"],
        "rf_6mhz": common + ["--input-frequency-mhz", "6"],
        "amplitude_1mvpk": common + ["--input-peak-v", "0.001"],
        "amplitude_20mvpk": common + ["--input-peak-v", "0.020"],
        "amplitude_50mvpk": common + ["--input-peak-v", "0.050"],
        "load_30pf_total": common + ["--output-damping-pf", "20"],
        "load_60pf_total": common + ["--output-damping-pf", "50"],
        "load_100kohm_shunt": common + ["--output-shunt-ohms", "100000"],
    }


def report_from_stdout(stdout: str) -> Path | None:
    candidates = [
        Path(line.split("=", 1)[1].strip())
        for line in stdout.splitlines() if line.startswith("report=")
    ]
    if not candidates:
        return None
    path = candidates[-1]
    return path if path.is_absolute() else ROOT / path


def run_case(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    path = report_from_stdout(completed.stdout)
    report = json.loads(path.read_text()) if path is not None and path.is_file() else None
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "report": str(path.relative_to(ROOT)) if path else None,
        "result": report,
        "stdout_tail": completed.stdout.splitlines()[-10:],
        "stderr_tail": completed.stderr.splitlines()[-10:],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gain_db(report: dict[str, Any]) -> float:
    output = float(report["analysis"]["output_tone_rms_v"])
    input_peak = float(report["input_peak_v"])
    return 20.0 * math.log10(output / input_peak)


def evaluate(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text())
    extraction = json.loads(EXTRACTION.read_text())
    frozen_hash = contract["output_checkpoint"]["sha256"]
    base_hash = extraction["sha256"]["base"]
    baseline = json.loads(BASELINE.read_text())
    errors: list[str] = []
    warnings: list[str] = []
    if baseline.get("status") != "pass":
        errors.append("Gate-4 base nominal reference is not passing")
    if baseline.get("gds_sha256") != frozen_hash or baseline.get("netlist_sha256") != base_hash:
        errors.append("Gate-4 base nominal reference is stale")
    for name, item in sorted(results.items()):
        report = item.get("result")
        if item.get("returncode") != 0 or not isinstance(report, dict):
            errors.append(f"{name}: simulation did not produce a report")
            continue
        if report.get("status") != "pass":
            errors.append(f"{name}: simulation failed: {report.get('errors')}")
        if report.get("gds_sha256") != frozen_hash or report.get("netlist_sha256") != base_hash:
            errors.append(f"{name}: report is bound to stale physical artifacts")

    metrics: dict[str, Any] = {}
    if not errors:
        reports = {name: item["result"] for name, item in results.items()}
        nominal_gain = gain_db(baseline)
        gains = {name: gain_db(report) for name, report in reports.items()}
        small_gain = gains["amplitude_1mvpk"]
        nominal_linearity_error = abs(nominal_gain - small_gain)
        compression = {
            name: small_gain - gains[name]
            for name in ("amplitude_20mvpk", "amplitude_50mvpk")
        }
        frequency_delta = {
            name: gains[name] - nominal_gain for name in ("rf_4p5mhz", "rf_6mhz")
        }
        load_delta = {
            name: gains[name] - nominal_gain
            for name in ("load_30pf_total", "load_60pf_total", "load_100kohm_shunt")
        }
        metrics = {
            "nominal_5mvpk_gain_db": nominal_gain,
            "small_signal_1mvpk_gain_db": small_gain,
            "nominal_linearity_error_db": nominal_linearity_error,
            "compression_db": compression,
            "frequency_gain_delta_db": frequency_delta,
            "load_gain_delta_db": load_delta,
            "output_common_mode_v": {
                name: report["analysis"]["output_common_mode_v"]
                for name, report in reports.items()
            },
        }
        if nominal_linearity_error > 1.0:
            errors.append(
                f"nominal 5 mV input is already compressed by {nominal_linearity_error:.3f} dB"
            )
        for name, value in frequency_delta.items():
            if abs(value) > 6.0:
                warnings.append(f"{name}: conversion gain moves by {value:.3f} dB")
        for name, value in load_delta.items():
            if value < -3.0:
                warnings.append(f"{name}: load reduces conversion gain by {-value:.3f} dB")
        if compression["amplitude_20mvpk"] >= 1.0:
            warnings.append("1 dB compression occurs below or at 20 mV peak input")
        elif compression["amplitude_50mvpk"] < 1.0:
            metrics["input_p1db_bound"] = ">50 mV peak"
        else:
            metrics["input_p1db_bound"] = "between 20 and 50 mV peak"

    return {
        "schema_version": 1,
        "gate": 5,
        "scope": "bounded base-extracted RF/amplitude/load sensitivity pilot",
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
                "status": (
                    item.get("result", {}).get("status")
                    if isinstance(item.get("result"), dict) else "missing"
                ),
            }
            for name, item in sorted(results.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4:
        raise SystemExit("jobs must be between one and four")
    work = cases(args.timeout)
    results: dict[str, dict[str, Any]] = {}
    if args.resume and args.report.is_file():
        prior = json.loads(args.report.read_text())
        for name, item in prior.get("cases", {}).items():
            path = ROOT / item.get("report", "")
            if name not in work or not path.is_file():
                continue
            report = json.loads(path.read_text())
            results[name] = {
                "name": name, "command": work[name], "returncode": 0,
                "report": str(path.relative_to(ROOT)), "result": report,
            }
            print(f"{name}: reused {report.get('status')}", flush=True)
    pending = {name: command for name, command in work.items() if name not in results}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        future_map = {
            pool.submit(run_case, name, command): name for name, command in pending.items()
        }
        for future in concurrent.futures.as_completed(future_map):
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
