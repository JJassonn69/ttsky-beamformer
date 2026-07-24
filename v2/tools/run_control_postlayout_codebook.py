#!/usr/bin/env python3
"""Run and summarize the complete 4x4 extracted V2 receive codebook."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "v2/tools/run_control_postlayout_smoke.py"
BUILD = ROOT / "build/v2/postlayout_smoke"
DEFAULT_GDS = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
DEFAULT_NETLISTS = {
    "base": ROOT / "build/v2/control_routing/final_rc/control_final_base.spice",
    "rc": ROOT / "build/v2/control_routing/final_rc/control_final_rc.spice",
}


def pvt_suffix(
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
) -> str:
    if process_corner == "tt" and supply_voltage_v == 1.8 and temperature_c == 27.0:
        return ""
    return (
        f"_corner_{process_corner}_vdd_{supply_voltage_v:g}"
        f"_temp_{temperature_c:g}c"
    ).replace(".", "p").replace("-", "m")


def parse_trim_codes(value: str) -> tuple[int, int, int, int]:
    try:
        codes = tuple(int(item, 0) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("trim codes must be four integers") from error
    if len(codes) != 4 or any(code < 0 or code > 15 for code in codes):
        raise argparse.ArgumentTypeError(
            "trim codes must be four comma-separated values from 0 through 15"
        )
    return codes  # type: ignore[return-value]


def case_report_path(
    view: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float = 0.005,
    startup: str = "op",
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
    trim_codes: tuple[int, int, int, int] = (8, 8, 8, 8),
    transient_step_ns: float = 2.0,
    passive_corner: str = "tt",
) -> Path:
    if startup not in ("uic", "op"):
        raise ValueError("startup must be 'uic' or 'op'")
    case_label = f"selected_{selected_beam}_incident_{incident_beam}"
    if input_peak_v != 0.005:
        case_label += f"_vin_{round(input_peak_v * 1e9):d}nv"
    if startup == "op":
        case_label += "_startup_op"
    if transient_step_ns != 2.0:
        case_label += f"_step_{transient_step_ns:g}ns".replace(".", "p")
    case_label += pvt_suffix(process_corner, supply_voltage_v, temperature_c)
    if passive_corner != "tt":
        case_label += f"_passives_{passive_corner}"
    if trim_codes != (8, 8, 8, 8):
        case_label += "_trim_" + "_".join(str(code) for code in trim_codes)
    return (
        BUILD / view / "codebook"
        / case_label
        / "report.json"
    )


def summary_report_path(
    view: str,
    *,
    startup: str = "op",
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
    trim_codes: tuple[int, int, int, int] = (8, 8, 8, 8),
    transient_step_ns: float = 2.0,
    passive_corner: str = "tt",
) -> Path:
    if startup not in ("uic", "op"):
        raise ValueError("startup must be 'uic' or 'op'")
    name = "summary_startup_op.json" if startup == "op" else "summary_uic.json"
    if transient_step_ns != 2.0:
        name = (
            name.removesuffix(".json")
            + f"_step_{transient_step_ns:g}ns".replace(".", "p")
            + ".json"
        )
    suffix = pvt_suffix(process_corner, supply_voltage_v, temperature_c)
    if suffix:
        name = name.removesuffix(".json") + suffix + ".json"
    if trim_codes != (8, 8, 8, 8):
        name = (
            name.removesuffix(".json")
            + "_trim_"
            + "_".join(str(code) for code in trim_codes)
            + ".json"
        )
    if passive_corner != "tt":
        name = name.removesuffix(".json") + f"_passives_{passive_corner}.json"
    return BUILD / view / "codebook" / name


def evaluate_matrix(
    matrix_v_rms: list[list[float]],
    minimum_rejection_db: float = 6.0,
    maximum_constructive_spread_db: float = 3.0,
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
        if diagonal_spread_db > maximum_constructive_spread_db:
            errors.append(
                f"constructive spread {diagonal_spread_db:.3f} dB exceeds "
                f"{maximum_constructive_spread_db:.3f} dB"
            )
    return {
        "response_matrix_v_rms": matrix_v_rms,
        "constructive_diagonal_v_rms": diagonal,
        "row_rejection_db": row_rejection_db,
        "minimum_rejection_db": min(row_rejection_db),
        "constructive_spread_db": diagonal_spread_db,
        "maximum_constructive_spread_db": maximum_constructive_spread_db,
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


def validate_case_identity(
    report: dict[str, Any],
    *,
    view: str,
    startup: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float,
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
    trim_codes: tuple[int, int, int, int] = (8, 8, 8, 8),
    transient_step_ns: float = 2.0,
    passive_corner: str = "tt",
) -> list[str]:
    """Reject stale case reports that do not describe the requested run."""
    expected = {
        "view": view,
        "startup": startup,
        "selected_beam": selected_beam,
        "incident_beam": incident_beam,
        "input_peak_v": input_peak_v,
        "process_corner": process_corner,
        "supply_voltage_v": supply_voltage_v,
        "temperature_c": temperature_c,
        "transient_step_ns": transient_step_ns,
    }
    errors: list[str] = []
    for field, value in expected.items():
        if report.get(field) != value:
            errors.append(
                f"case identity {field}={report.get(field)!r}, expected {value!r}"
            )
    if trim_codes != (8, 8, 8, 8) or "trim_codes" in report:
        if report.get("trim_codes") != list(trim_codes):
            errors.append(
                f"case identity trim_codes={report.get('trim_codes')!r}, "
                f"expected {list(trim_codes)!r}"
            )
    if passive_corner != "tt" or "passive_corner" in report:
        if report.get("passive_corner") != passive_corner:
            errors.append(
                f"case identity passive_corner={report.get('passive_corner')!r}, "
                f"expected {passive_corner!r}"
            )
    for field in ("gds_sha256", "netlist_sha256", "spiceinit_sha256"):
        value = report.get(field)
        if not isinstance(value, str) or len(value) != 64:
            errors.append(f"case identity lacks a valid {field}")
    return errors


def validate_settled_measurements(report: dict[str, Any]) -> list[str]:
    """Apply release bias checks even when aggregating preserved reports."""
    measurements = report.get("measurements")
    if not isinstance(measurements, dict):
        return ["case report lacks measurements"]
    errors: list[str] = []
    checks = (
        ("vcm_avg", 1.1, 1.3, "VCM"),
        ("common_mode_avg", 0.8, 1.2, "output common mode"),
    )
    for field, lower, upper, label in checks:
        value = measurements.get(field)
        if not isinstance(value, (int, float)) or not lower < float(value) < upper:
            errors.append(f"settled {label} is outside {lower:g}..{upper:g} V")
    supply = measurements.get("supply_avg")
    if not isinstance(supply, (int, float)) or abs(float(supply)) < 1e-6:
        errors.append("settled case draws no measurable supply current")
    return errors


def case_report_is_reusable(
    report: dict[str, Any],
    *,
    view: str,
    startup: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float,
    gds_sha256: str,
    netlist_sha256: str,
    process_corner: str = "tt",
    supply_voltage_v: float = 1.8,
    temperature_c: float = 27.0,
    trim_codes: tuple[int, int, int, int] = (8, 8, 8, 8),
    transient_step_ns: float = 2.0,
    passive_corner: str = "tt",
) -> bool:
    if report.get("status") != "pass":
        return False
    if report.get("gds_sha256") != gds_sha256:
        return False
    if report.get("netlist_sha256") != netlist_sha256:
        return False
    if validate_case_identity(
        report,
        view=view,
        startup=startup,
        selected_beam=selected_beam,
        incident_beam=incident_beam,
        input_peak_v=input_peak_v,
        process_corner=process_corner,
        supply_voltage_v=supply_voltage_v,
        temperature_c=temperature_c,
        trim_codes=trim_codes,
        transient_step_ns=transient_step_ns,
        passive_corner=passive_corner,
    ):
        return False
    return startup != "op" or not validate_settled_measurements(report)


def operating_ranges(
    reports: dict[tuple[int, int, float], dict[str, Any]],
    supply_voltage_v: float = 1.8,
) -> dict[str, list[float]]:
    def values(field: str, *, absolute: bool = False) -> list[float]:
        result = [
            float(report["measurements"][field]) for report in reports.values()
        ]
        if absolute:
            result = [abs(value) for value in result]
        return result

    vcm = values("vcm_avg")
    common_mode = values("common_mode_avg")
    supply_current = values("supply_avg", absolute=True)
    return {
        "vcm_v": [min(vcm), max(vcm)],
        "output_common_mode_v": [min(common_mode), max(common_mode)],
        "supply_current_a": [min(supply_current), max(supply_current)],
        "estimated_power_w": [
            supply_voltage_v * min(supply_current),
            supply_voltage_v * max(supply_current),
        ],
    }


def run_case(
    view: str,
    selected_beam: int,
    incident_beam: int,
    input_peak_v: float,
    ngspice: str,
    timeout: int,
    startup: str,
    process_corner: str,
    supply_voltage_v: float,
    temperature_c: float,
    trim_codes: tuple[int, int, int, int],
    transient_step_ns: float,
    passive_corner: str,
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
        "--process-corner", process_corner,
        "--supply-voltage-v", str(supply_voltage_v),
        "--temperature-c", str(temperature_c),
        "--trim-codes", ",".join(str(code) for code in trim_codes),
        "--transient-step-ns", str(transient_step_ns),
        "--passive-corner", passive_corner,
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
    parser.add_argument(
        "--process-corner", choices=("tt", "ff", "ss", "fs", "sf"), default="tt"
    )
    parser.add_argument("--supply-voltage-v", type=float, default=1.8)
    parser.add_argument("--temperature-c", type=float, default=27.0)
    parser.add_argument("--transient-step-ns", type=float, default=2.0)
    parser.add_argument(
        "--passive-corner", choices=("tt", "hh", "hl", "lh", "ll"), default="tt"
    )
    parser.add_argument(
        "--trim-codes",
        type=parse_trim_codes,
        default=(8, 8, 8, 8),
        metavar="CH0,CH1,CH2,CH3",
    )
    parser.add_argument("--minimum-rejection-db", type=float, default=6.0)
    parser.add_argument(
        "--maximum-constructive-spread-db",
        type=float,
        default=3.0,
    )
    parser.add_argument(
        "--startup",
        choices=("uic", "op"),
        default="op",
        help=(
            "exact DC operating-point startup (release default) or ramped UIC "
            "startup for diagnostic smoke testing"
        ),
    )
    reuse_group = parser.add_mutually_exclusive_group()
    reuse_group.add_argument(
        "--reuse-reports",
        action="store_true",
        help="aggregate and validate existing case reports without rerunning ngspice",
    )
    reuse_group.add_argument(
        "--resume",
        action="store_true",
        help="reuse only exact current passing reports and run every missing case",
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        raise SystemExit("--jobs must be between one and four")
    if not 1.4 <= args.supply_voltage_v <= 2.1:
        raise SystemExit("--supply-voltage-v must be between 1.4 and 2.1")
    if not -55.0 <= args.temperature_c <= 125.0:
        raise SystemExit("--temperature-c must be between -55 and 125")
    if not 0.5 <= args.transient_step_ns <= 10.0:
        raise SystemExit("--transient-step-ns must be between 0.5 and 10")

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
    reused_case_count = 0
    if args.reuse_reports:
        executions = [
            (selected, incident, input_peak_v, 0, "")
            for selected, incident, input_peak_v in cases
        ]
    else:
        pending_cases = cases
        if args.resume:
            current_gds_hash = hashlib.sha256(DEFAULT_GDS.read_bytes()).hexdigest()
            current_netlist_hash = hashlib.sha256(
                DEFAULT_NETLISTS[args.view].read_bytes()
            ).hexdigest()
            pending_cases = []
            for selected, incident, input_peak_v in cases:
                path = case_report_path(
                    args.view,
                    selected,
                    incident,
                    input_peak_v,
                    startup=args.startup,
                    process_corner=args.process_corner,
                    supply_voltage_v=args.supply_voltage_v,
                    temperature_c=args.temperature_c,
                    trim_codes=args.trim_codes,
                    transient_step_ns=args.transient_step_ns,
                    passive_corner=args.passive_corner,
                )
                report = (
                    json.loads(path.read_text(encoding="utf-8"))
                    if path.is_file()
                    else {}
                )
                if case_report_is_reusable(
                    report,
                    view=args.view,
                    startup=args.startup,
                    selected_beam=selected,
                    incident_beam=incident,
                    input_peak_v=input_peak_v,
                    gds_sha256=current_gds_hash,
                    netlist_sha256=current_netlist_hash,
                    process_corner=args.process_corner,
                    supply_voltage_v=args.supply_voltage_v,
                    temperature_c=args.temperature_c,
                    trim_codes=args.trim_codes,
                    transient_step_ns=args.transient_step_ns,
                    passive_corner=args.passive_corner,
                ):
                    executions.append((selected, incident, input_peak_v, 0, ""))
                    reused_case_count += 1
                else:
                    pending_cases.append((selected, incident, input_peak_v))
            print(
                f"resume reused={reused_case_count} pending={len(pending_cases)}",
                flush=True,
            )
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
                    args.process_corner,
                    args.supply_voltage_v,
                    args.temperature_c,
                    args.trim_codes,
                    args.transient_step_ns,
                    args.passive_corner,
                )
                for selected, incident, input_peak_v in pending_cases
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
            process_corner=args.process_corner,
            supply_voltage_v=args.supply_voltage_v,
            temperature_c=args.temperature_c,
            trim_codes=args.trim_codes,
            transient_step_ns=args.transient_step_ns,
            passive_corner=args.passive_corner,
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
        identity_errors = validate_case_identity(
            report,
            view=args.view,
            startup=args.startup,
            selected_beam=selected,
            incident_beam=incident,
            input_peak_v=input_peak_v,
            process_corner=args.process_corner,
            supply_voltage_v=args.supply_voltage_v,
            temperature_c=args.temperature_c,
            trim_codes=args.trim_codes,
            transient_step_ns=args.transient_step_ns,
            passive_corner=args.passive_corner,
        )
        errors.extend(
            f"selected beam {selected}, incident beam {incident}: {message}"
            for message in identity_errors
        )
        if args.startup == "op":
            errors.extend(
                f"selected beam {selected}, incident beam {incident}: {message}"
                for message in validate_settled_measurements(report)
            )
        if report.get("status") != "pass":
            errors.append(
                f"selected beam {selected}, incident beam {incident} "
                f"reported {report.get('status')}: {report.get('errors')}"
            )

    matrix: list[list[float]] = []
    raw_matrix: list[list[float]] = []
    background_iq: list[list[float]] = []
    if len(reports) == 20:
        gds_hashes = sorted({str(report.get("gds_sha256")) for report in reports.values()})
        netlist_hashes = sorted(
            {str(report.get("netlist_sha256")) for report in reports.values()}
        )
        spiceinit_hashes = sorted(
            {str(report.get("spiceinit_sha256")) for report in reports.values()}
        )
        varactor_model_hashes = sorted({
            str(report.get("extracted_varactor_model_sha256"))
            for report in reports.values()
        })
        if len(gds_hashes) != 1:
            errors.append(f"case reports use multiple GDS hashes: {gds_hashes}")
        if len(netlist_hashes) != 1:
            errors.append(f"case reports use multiple netlist hashes: {netlist_hashes}")
        if len(spiceinit_hashes) != 1:
            errors.append(
                f"case reports use multiple ngspice startup hashes: {spiceinit_hashes}"
            )
        if len(varactor_model_hashes) != 1 or varactor_model_hashes == ["None"]:
            errors.append(
                "case reports lack one consistent extracted-varactor model hash: "
                f"{varactor_model_hashes}"
            )
        corrected_matrix, raw_matrix, background_iq = corrected_response_matrices(reports)
        # Release acceptance is deliberately based on the uncorrected response.
        # A zero-input subtraction is useful for diagnosis, but silicon cannot
        # perform that subtraction unless cancellation hardware is implemented.
        matrix = raw_matrix
        metrics, matrix_errors = evaluate_matrix(
            raw_matrix,
            args.minimum_rejection_db,
            args.maximum_constructive_spread_db,
        )
        metrics["raw_response_matrix_v_rms"] = raw_matrix
        metrics["baseline_corrected_response_matrix_v_rms"] = corrected_matrix
        metrics["zero_input_background_iq_v"] = background_iq
        metrics["acceptance_basis"] = "raw_unsubtracted_response"
        metrics["artifact_hashes"] = {
            "gds_sha256": gds_hashes,
            "netlist_sha256": netlist_hashes,
            "spiceinit_sha256": spiceinit_hashes,
            "extracted_varactor_model_sha256": varactor_model_hashes,
        }
        metrics["settled_operating_ranges"] = operating_ranges(
            reports, args.supply_voltage_v
        )
        errors.extend(matrix_errors)
    else:
        metrics = {"response_matrix_v_rms": matrix}

    result_path = summary_report_path(
        args.view,
        startup=args.startup,
        process_corner=args.process_corner,
        supply_voltage_v=args.supply_voltage_v,
        temperature_c=args.temperature_c,
        trim_codes=args.trim_codes,
        transient_step_ns=args.transient_step_ns,
        passive_corner=args.passive_corner,
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    case_reports = []
    for selected, incident, input_peak_v in sorted(reports):
        path = case_report_path(
            args.view,
            selected,
            incident,
            input_peak_v,
            startup=args.startup,
            process_corner=args.process_corner,
            supply_voltage_v=args.supply_voltage_v,
            temperature_c=args.temperature_c,
            trim_codes=args.trim_codes,
            transient_step_ns=args.transient_step_ns,
            passive_corner=args.passive_corner,
        )
        report = reports[(selected, incident, input_peak_v)]
        case_reports.append({
            "selected_beam": selected,
            "incident_beam": incident,
            "input_peak_v": input_peak_v,
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "status": report.get("status"),
            "timed_out": bool(report.get("timed_out")),
            "gds_sha256": report.get("gds_sha256"),
            "netlist_sha256": report.get("netlist_sha256"),
            "spiceinit_sha256": report.get("spiceinit_sha256"),
            "extracted_varactor_model_sha256": report.get(
                "extracted_varactor_model_sha256"
            ),
        })
    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "view": args.view,
        "startup": args.startup,
        "process_corner": args.process_corner,
        "supply_voltage_v": args.supply_voltage_v,
        "temperature_c": args.temperature_c,
        "trim_codes": list(args.trim_codes),
        "transient_step_ns": args.transient_step_ns,
        "passive_corner": args.passive_corner,
        "jobs": args.jobs,
        "reused_reports": args.reuse_reports,
        "resumed": args.resume,
        "resumed_case_count": reused_case_count,
        "case_count": len(reports),
        "signal_case_count": sum(key[2] == 0.005 for key in reports),
        "baseline_case_count": sum(key[2] == 0.0 for key in reports),
        "case_reports": case_reports,
        "functional_rejection_gate_db": args.minimum_rejection_db,
        "constructive_spread_gate_db": args.maximum_constructive_spread_db,
        "metrics": metrics,
    }
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"report={result_path}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
