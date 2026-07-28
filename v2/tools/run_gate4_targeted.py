#!/usr/bin/env python3
"""Run the bounded Gate-4 electrical matrix for the frozen V2 candidate."""

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
STARTUP = ROOT / "v2/tools/run_control_postlayout_startup.py"
CONTRACT = ROOT / "v2/layout/vcm_varactor_eco.json"

KNOWN_REPORTS = {
    "base_nominal_constructive": "build/v2/postlayout_smoke/base/codebook/selected_0_incident_0_startup_op_step_5ns/report.json",
    "base_zero_input_background": "build/v2/postlayout_smoke/base/codebook/selected_0_incident_1_vin_0nv_startup_op_step_5ns/report.json",
    "rc_nominal_constructive": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_0_startup_op_step_5ns/report.json",
    "rc_representative_null": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_1_startup_op_step_5ns/report.json",
    "rc_zero_input_background": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_1_vin_0nv_startup_op_step_5ns/report.json",
    "rc_sf_headroom": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_0_vin_0nv_startup_op_window_2us_3us_step_10ns_corner_sf_vdd_1p8_temp_27c_passives_hh/report.json",
    "rc_ff_headroom": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_0_vin_0nv_startup_op_window_2us_3us_step_10ns_corner_ff_vdd_1p98_temp_m40c_passives_hh/report.json",
    "rc_trim_low": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_0_startup_op_step_5ns_trim_0_0_0_0/report.json",
    "rc_trim_high": "build/v2/postlayout_smoke/rc/codebook/selected_0_incident_0_startup_op_step_5ns_trim_15_15_15_15/report.json",
    "rc_cold_start": "build/v2/postlayout_startup/rc/quiet_120us_step_20ns_final_5us/report.json",
}


def cases(timeout: int) -> dict[str, list[str]]:
    smoke_common = [
        "python3", str(SMOKE), "--startup", "op",
        "--analysis-start-us", "2", "--analysis-stop-us", "4",
        "--transient-step-ns", "5", "--timeout", str(timeout),
    ]
    headroom_common = [
        "python3", str(SMOKE), "--view", "rc", "--startup", "op",
        "--beam", "0", "--incident-beam", "0", "--input-peak-v", "0",
        "--analysis-start-us", "2", "--analysis-stop-us", "3",
        "--transient-step-ns", "10", "--timeout", str(timeout),
    ]
    return {
        "base_nominal_constructive": smoke_common + [
            "--view", "base", "--beam", "0", "--incident-beam", "0",
        ],
        "base_zero_input_background": smoke_common + [
            "--view", "base", "--beam", "0", "--incident-beam", "1",
            "--input-peak-v", "0",
        ],
        "rc_nominal_constructive": smoke_common + [
            "--view", "rc", "--beam", "0", "--incident-beam", "0",
        ],
        "rc_representative_null": smoke_common + [
            "--view", "rc", "--beam", "0", "--incident-beam", "1",
        ],
        "rc_zero_input_background": smoke_common + [
            "--view", "rc", "--beam", "0", "--incident-beam", "1",
            "--input-peak-v", "0",
        ],
        "rc_sf_headroom": headroom_common + [
            "--process-corner", "sf", "--supply-voltage-v", "1.8",
            "--temperature-c", "27", "--passive-corner", "hh",
        ],
        "rc_ff_headroom": headroom_common + [
            "--process-corner", "ff", "--supply-voltage-v", "1.98",
            "--temperature-c", "-40", "--passive-corner", "hh",
        ],
        "rc_trim_low": smoke_common + [
            "--view", "rc", "--beam", "0", "--incident-beam", "0",
            "--trim-codes", "0,0,0,0",
        ],
        "rc_trim_high": smoke_common + [
            "--view", "rc", "--beam", "0", "--incident-beam", "0",
            "--trim-codes", "15,15,15,15",
        ],
        "rc_cold_start": [
            "python3", str(STARTUP), "--view", "rc", "--stop-us", "120",
            "--step-ns", "20", "--final-window-us", "5",
            "--timeout", str(timeout),
        ],
    }


def run_case(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False,
    )
    report_lines = [
        line.split("=", 1)[1].strip()
        for line in completed.stdout.splitlines() if line.startswith("report=")
    ]
    report_path = Path(report_lines[-1]) if report_lines else None
    if report_path is not None and not report_path.is_absolute():
        report_path = ROOT / report_path
    report = (
        json.loads(report_path.read_text())
        if report_path is not None and report_path.is_file() else None
    )
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "report": str(report_path.relative_to(ROOT)) if report_path else None,
        "result": report,
        "stderr_tail": completed.stderr.splitlines()[-20:],
        "stdout_tail": completed.stdout.splitlines()[-20:],
    }


def tone_iq(case: dict[str, Any]) -> tuple[float, float]:
    analysis = case["result"]["analysis"]
    return float(analysis["output_tone_i_v"]), float(analysis["output_tone_q_v"])


def extraction_binding(extraction: dict[str, Any]) -> dict[str, Any]:
    """Return host-independent fields that define the extracted electrical view."""
    return {
        "status": extraction.get("status"),
        "sha256": extraction.get("sha256"),
        "base": extraction.get("base"),
        "distributed_rc": {
            key: extraction.get("distributed_rc", {}).get(key)
            for key in (
                "capacitors", "devices", "resistors", "internal_resistor_nodes",
                "covered_manifest_nets",
            )
        },
        "required_routed_net_count": extraction.get("required_routed_net_count"),
        "covered_routed_net_count": extraction.get("covered_routed_net_count"),
        "uncovered_routed_nets": extraction.get("uncovered_routed_nets"),
        "checks": extraction.get("checks"),
    }


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def evaluate(
    results: dict[str, dict[str, Any]],
    frozen_hash: str,
    expected_netlist_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_netlist_hashes = expected_netlist_hashes or {}
    for name, item in sorted(results.items()):
        report = item.get("result")
        if item.get("returncode") != 0:
            errors.append(f"{name}: runner exited with {item.get('returncode')}")
        if not isinstance(report, dict):
            errors.append(f"{name}: report is missing")
            continue
        if report.get("status") != "pass":
            errors.append(f"{name}: report is not passing: {report.get('errors')}")
        if report.get("gds_sha256") != frozen_hash:
            errors.append(f"{name}: report is bound to a different GDS hash")
        view = report.get("view")
        if view in expected_netlist_hashes and report.get("netlist_sha256") != expected_netlist_hashes[view]:
            errors.append(f"{name}: report is bound to a stale {view} netlist")

    metrics: dict[str, float] = {}
    needed = {
        "base_nominal_constructive", "base_zero_input_background",
        "rc_nominal_constructive",
        "rc_representative_null", "rc_zero_input_background",
    }
    if needed <= results.keys() and all(
        isinstance(results[name].get("result"), dict) for name in needed
    ):
        base_i, base_q = tone_iq(results["base_nominal_constructive"])
        base_bg_i, base_bg_q = tone_iq(results["base_zero_input_background"])
        rc_i, rc_q = tone_iq(results["rc_nominal_constructive"])
        null_i, null_q = tone_iq(results["rc_representative_null"])
        bg_i, bg_q = tone_iq(results["rc_zero_input_background"])
        corrected_base = math.sqrt(
            2.0 * ((base_i - base_bg_i) ** 2 + (base_q - base_bg_q) ** 2)
        )
        corrected_wanted = math.sqrt(2.0 * ((rc_i - bg_i) ** 2 + (rc_q - bg_q) ** 2))
        corrected_null = math.sqrt(2.0 * ((null_i - bg_i) ** 2 + (null_q - bg_q) ** 2))
        rejection = (
            math.inf if corrected_null == 0.0
            else 20.0 * math.log10(corrected_wanted / corrected_null)
        )
        base_rc_delta = (
            math.inf if min(corrected_base, corrected_wanted) <= 0.0
            else 20.0 * math.log10(
                max(corrected_base, corrected_wanted)
                / min(corrected_base, corrected_wanted)
            )
        )
        metrics = {
            "base_corrected_constructive_rms_v": corrected_base,
            "rc_corrected_constructive_rms_v": corrected_wanted,
            "rc_corrected_null_rms_v": corrected_null,
            "rc_representative_rejection_db": rejection,
            "base_to_rc_constructive_delta_db": base_rc_delta,
        }
        if rejection < 6.0:
            errors.append(f"representative corrected rejection is only {rejection:.3f} dB")
        if base_rc_delta > 3.0:
            errors.append(f"base-to-RC constructive delta is {base_rc_delta:.3f} dB")

    return {
        "schema_version": 1,
        "gate": 4,
        "scope": "targeted electrical closure; not exhaustive characterization",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "frozen_gds_sha256": frozen_hash,
        "expected_netlist_sha256": expected_netlist_hashes,
        "case_count": len(results),
        "metrics": metrics,
        "cases": {
            name: {
                "report": item.get("report"),
                "returncode": item.get("returncode"),
                "status": (
                    item.get("result", {}).get("status")
                    if isinstance(item.get("result"), dict) else "missing"
                ),
                "report_sha256": (
                    hashlib.sha256((ROOT / item["report"]).read_bytes()).hexdigest()
                    if item.get("report") and (ROOT / item["report"]).is_file() else None
                ),
            }
            for name, item in sorted(results.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--resume", action="store_true",
        help="reuse hash-matching case reports already listed in the manifest",
    )
    parser.add_argument(
        "--report", type=Path,
        default=Path("build/v2/signoff/gate4_targeted_manifest.json"),
    )
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4:
        raise SystemExit("--jobs must be between 1 and 4")
    contract = json.loads(CONTRACT.read_text())
    frozen_hash = contract["output_checkpoint"]["sha256"]
    extraction_path = ROOT / "build/v2/control_routing/final_rc/coverage_audit.json"
    extraction = json.loads(extraction_path.read_text())
    if extraction.get("status") != "pass":
        raise SystemExit("frozen candidate distributed-RC extraction is not passing")
    expected_netlist_hashes = {
        "base": extraction["sha256"]["base"],
        "rc": extraction["sha256"]["distributed_rc"],
    }
    work = cases(args.timeout)
    results: dict[str, dict[str, Any]] = {}
    if args.resume:
        prior_cases = {}
        if args.report.is_file():
            prior_cases = json.loads(args.report.read_text()).get("cases", {})
        for name in work:
            item = prior_cases.get(name, {})
            relative = item.get("report") or KNOWN_REPORTS.get(name)
            path = ROOT / relative if relative else None
            if path is None or not path.is_file():
                continue
            result = json.loads(path.read_text())
            if result.get("gds_sha256") != frozen_hash:
                continue
            view = result.get("view")
            if view in expected_netlist_hashes and result.get("netlist_sha256") != expected_netlist_hashes[view]:
                continue
            results[name] = {
                "name": name, "command": work[name], "returncode": 0,
                "report": relative, "result": result,
                "stderr_tail": [], "stdout_tail": [],
            }
            print(f"{name}: reused {result.get('status')}", flush=True)
    pending = {name: command for name, command in work.items() if name not in results}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(run_case, name, command): name
            for name, command in pending.items()
        }
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            results[item["name"]] = item
            status = (
                item.get("result", {}).get("status")
                if isinstance(item.get("result"), dict) else "missing"
            )
            print(f"{item['name']}: {status} (returncode {item['returncode']})", flush=True)
    report = evaluate(results, frozen_hash, expected_netlist_hashes)
    report["extraction_report"] = str(extraction_path.relative_to(ROOT))
    report["extraction_report_sha256"] = hashlib.sha256(extraction_path.read_bytes()).hexdigest()
    report["extraction_binding"] = extraction_binding(extraction)
    report["extraction_binding_sha256"] = canonical_sha256(report["extraction_binding"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
