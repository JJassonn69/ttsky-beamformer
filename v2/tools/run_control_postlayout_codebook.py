#!/usr/bin/env python3
"""Run and summarize the complete 4x4 extracted V2 receive codebook."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "v2/tools/run_control_postlayout_smoke.py"
BUILD = ROOT / "build/v2/postlayout_smoke"


def case_report_path(
    view: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float = 0.005,
    startup: str = "op",
) -> Path:
    if startup not in ("uic", "op"):
        raise ValueError("startup must be 'uic' or 'op'")
    case_label = f"selected_{selected_beam}_incident_{incident_beam}"
    if input_peak_v != 0.005:
        case_label += f"_vin_{round(input_peak_v * 1e9):d}nv"
    if startup == "op":
        case_label += "_startup_op"
    return (
        BUILD / view / "codebook"
        / case_label
        / "report.json"
    )


def evaluate_matrix(
    matrix_v_rms: list[list[float]], minimum_rejection_db: float = 6.0
) -> tuple[dict[str, Any], list[str]]:
    if len(matrix_v_rms) != 4 or any(len(row) != 4 for row in matrix_v_rms):
        raise ValueError("codebook response matrix must be 4x4")
    errors: list[str] = []
    row_rejection_db: list[float] = []
    diagonal = [matrix_v_rms[index][index] for index in range(4)]
    for selected, row in enumerate(matrix_v_rms):
        off_beam = [value for incident, value in enumerate(row) if incident != selected]
        worst_off_beam = max(off_beam)
        wanted = row[selected]
        if wanted <= 0.0:
            rejection_db = -math.inf
        elif worst_off_beam <= 0.0:
            rejection_db = math.inf
        else:
            rejection_db = 20.0 * math.log10(wanted / worst_off_beam)
        row_rejection_db.append(rejection_db)
        if rejection_db < minimum_rejection_db:
            errors.append(
                f"selected beam {selected} rejection {rejection_db:.3f} dB "
                f"is below {minimum_rejection_db:.3f} dB"
            )
    if min(diagonal) <= 0.0:
        diagonal_spread_db = math.inf
        errors.append("at least one constructive diagonal response is zero")
    else:
        diagonal_spread_db = 20.0 * math.log10(max(diagonal) / min(diagonal))
    return {
        "response_matrix_v_rms": matrix_v_rms,
        "constructive_diagonal_v_rms": diagonal,
        "row_rejection_db": row_rejection_db,
        "minimum_rejection_db": min(row_rejection_db),
        "constructive_spread_db": diagonal_spread_db,
    }, errors


def corrected_response_matrices(
    reports: dict[tuple[int, int, float], dict[str, Any]],
) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    baselines = {
        selected: reports[(selected, (selected + 1) % 4, 0.0)]
        for selected in range(4)
    }
    background_iq = [
        [
            float(baselines[selected]["analysis"]["output_tone_i_v"]),
            float(baselines[selected]["analysis"]["output_tone_q_v"]),
        ]
        for selected in range(4)
    ]
    raw_matrix = [
        [
            float(
                reports[(selected, incident, 0.005)]["analysis"]
                ["output_tone_rms_v"]
            )
            for incident in range(4)
        ]
        for selected in range(4)
    ]
    corrected_matrix: list[list[float]] = []
    for selected in range(4):
        row: list[float] = []
        baseline_i, baseline_q = background_iq[selected]
        for incident in range(4):
            analysis = reports[(selected, incident, 0.005)]["analysis"]
            signal_i = float(analysis["output_tone_i_v"]) - baseline_i
            signal_q = float(analysis["output_tone_q_v"]) - baseline_q
            row.append(math.sqrt(2.0 * (signal_i * signal_i + signal_q * signal_q)))
        corrected_matrix.append(row)
    return corrected_matrix, raw_matrix, background_iq


def run_case(
    view: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float,
    ngspice: str,
    timeout: int,
    startup: str,
) -> tuple[int, int, float, int, str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--view", view,
        "--beam", str(selected_beam),
        "--incident-beam", str(incident_beam),
        "--input-peak-v", str(input_peak_v),
        "--ngspice", ngspice,
        "--timeout", str(timeout),
        "--startup", startup,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    return selected_beam, incident_beam, input_peak_v, completed.returncode, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="base")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--minimum-rejection-db", type=float, default=6.0)
    parser.add_argument(
        "--startup",
        choices=("uic", "op"),
        default="op",
        help=(
            "exact DC operating-point startup (release default) or ramped UIC "
            "startup for diagnostic smoke testing"
        ),
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        raise SystemExit("--jobs must be between one and four")

    signal_cases = [
        (selected, incident, 0.005)
        for selected in range(4) for incident in range(4)
    ]
    baseline_cases = [
        (selected, (selected + 1) % 4, 0.0)
        for selected in range(4)
    ]
    cases = baseline_cases + signal_cases
    executions: list[tuple[int, int, float, int, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [
            executor.submit(
                run_case,
                args.view,
                selected,
                incident,
                input_peak_v,
                args.ngspice,
                args.timeout,
                args.startup,
            )
            for selected, incident, input_peak_v in cases
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            executions.append(result)
            selected, incident, input_peak_v, returncode, _ = result
            kind = "baseline" if input_peak_v == 0.0 else "signal"
            print(
                f"kind={kind} selected={selected} incident={incident} "
                f"returncode={returncode}",
                flush=True,
            )

    errors: list[str] = []
    reports: dict[tuple[int, int, float], dict[str, Any]] = {}
    for selected, incident, input_peak_v, returncode, output in executions:
        path = case_report_path(
            args.view,
            selected,
            incident,
            input_peak_v,
            startup=args.startup,
        )
        if returncode:
            errors.append(
                f"selected beam {selected}, incident beam {incident} failed: "
                f"return code {returncode}; output tail={output[-1000:]!r}"
            )
        if not path.is_file():
            errors.append(f"missing case report: {path}")
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        reports[(selected, incident, input_peak_v)] = report
        if report.get("status") != "pass":
            errors.append(
                f"selected beam {selected}, incident beam {incident} "
                f"reported {report.get('status')}: {report.get('errors')}"
            )

    matrix: list[list[float]] = []
    raw_matrix: list[list[float]] = []
    background_iq: list[list[float]] = []
    if len(reports) == 20:
        corrected_matrix, raw_matrix, background_iq = corrected_response_matrices(reports)
        # Release acceptance is deliberately based on the uncorrected response.
        # A zero-input subtraction is useful for diagnosis, but silicon cannot
        # perform that subtraction unless cancellation hardware is implemented.
        matrix = raw_matrix
        metrics, matrix_errors = evaluate_matrix(raw_matrix, args.minimum_rejection_db)
        metrics["raw_response_matrix_v_rms"] = raw_matrix
        metrics["baseline_corrected_response_matrix_v_rms"] = corrected_matrix
        metrics["zero_input_background_iq_v"] = background_iq
        metrics["acceptance_basis"] = "raw_unsubtracted_response"
        errors.extend(matrix_errors)
    else:
        metrics = {"response_matrix_v_rms": matrix}

    summary_name = "summary_startup_op.json" if args.startup == "op" else "summary_uic.json"
    result_path = BUILD / args.view / "codebook" / summary_name
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "startup": args.startup,
        "jobs": args.jobs,
        "case_count": len(reports),
        "signal_case_count": sum(key[2] == 0.005 for key in reports),
        "baseline_case_count": sum(key[2] == 0.0 for key in reports),
        "functional_rejection_gate_db": args.minimum_rejection_db,
        "metrics": metrics,
    }
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"report={result_path}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
