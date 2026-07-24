#!/usr/bin/env python3
"""Run a bounded post-layout MOS-mismatch pilot on the frozen V2 candidate.

The open SKY130 ngspice model files publish geometry-scaled mismatch
coefficients, but their per-instance Spectre ``statistics`` directives are
comments in ngspice.  This tool makes that missing step explicit: it gives
every extracted MOS instance independent, seeded standard-normal factors and
passes them into locally patched copies of the unmodified PDK model subcircuits.

This is a PDK-coefficient MOS-mismatch sensitivity screen.  It is not a
foundry-qualified Monte Carlo claim: passive mismatch, spatial correlation,
package variation, and proprietary model effects are intentionally excluded.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from run_control_postlayout_smoke import (
    DEFAULT_BASE,
    DEFAULT_GDS,
    DEFAULT_RC,
    DEFAULT_VARACTOR_MODEL,
    SPICE_INIT,
    analyze,
    codebook_input_phases,
    deck_text,
    extracted_model_names,
    parse_measures,
    prepare_runtime,
    sha256,
)


ROOT = Path(__file__).resolve().parents[2]
BUILD = Path("build/v2/gate5_mismatch_pilot")
MODEL_METHOD = (
    "independent per-instance standard-normal MOS factors applied to published "
    "SKY130 geometry-scaled mismatch coefficients"
)
MODEL_LIMITATIONS = [
    "not foundry-qualified Monte Carlo",
    "no passive mismatch",
    "no spatial correlation or systematic gradient",
    "no package variation",
]
LOD_PARAMETERS = Path("third_party/sky130_fd_pr/models/parameters/lod.spice")
FIXED_MODEL_PARAMETERS = {
    "sky130_fd_pr__nfet_01v8__dlc_rotweak": 0,
    "sky130_fd_pr__pfet_01v8__dlc_rotweak": 0,
}

MODEL_SPECS = {
    "sky130_fd_pr__nfet_01v8": {
        "pm3": Path("third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__tt.pm3.spice"),
        "corner": Path("third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__tt.corner.spice"),
        "mismatch": Path("third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__mismatch.corner.spice"),
        "parameters": ("toxe", "vth0", "voff"),
    },
    "sky130_fd_pr__pfet_01v8_hvt": {
        "pm3": Path("third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__tt.pm3.spice"),
        "corner": Path("third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__tt.corner.spice"),
        "mismatch": Path("third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"),
        "parameters": ("toxe", "vth0", "voff", "nfactor"),
    },
}
SPECIAL_NFET = "sky130_fd_pr__special_nfet_01v8"
NOMINAL_MODEL_BLOCK = "\n".join((
    '.include "spice/sky130/sky130_1v8_tt.inc"',
    '.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__tt.corner.spice"',
    '.include "third_party/sky130_fd_pr_hvt/sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice"',
))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def zero_failure_lower_bound(sample_count: int, alpha: float = 0.05) -> float:
    """Return the exact one-sided binomial pass-probability lower bound."""
    if sample_count < 1:
        raise ValueError("sample count must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")
    return alpha ** (1.0 / sample_count)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_absolute() else path)


def patch_pm3(text: str, model: str, parameters: tuple[str, ...]) -> str:
    """Expose the PDK's Spectre mismatch factors as subcircuit parameters."""
    match = re.search(
        rf"(?m)^(\.subckt\s+{re.escape(model)}\s+d\s+g\s+s\s+b)\s*\n\+\s*$",
        text,
    )
    if not match:
        raise ValueError(f"cannot find unique subcircuit header for {model}")
    local_names = {name: f"mc_{model.split('__')[-1]}_{name}" for name in parameters}
    continuation = " ".join(f"{local}=0" for local in local_names.values())
    patched = text[:match.start()] + match.group(1) + f"\n+ {continuation}" + text[match.end():]
    body_start = patched.index("\n", match.start())
    prefix, body = patched[:body_start], patched[body_start:]
    for name, local in local_names.items():
        global_name = f"{model}__{name}_slope_spectre"
        occurrences = body.count(global_name)
        if occurrences < 1:
            raise ValueError(f"{model} model does not consume {global_name}")
        body = body.replace(global_name, f"({global_name}+{local})")
    return prefix + body


def patch_corner(text: str, original_pm3: Path, patched_pm3: Path) -> str:
    original = f'.include "{original_pm3.name}"'
    replacement = f'.include "{relative(patched_pm3)}"'
    if text.count(original) != 1:
        raise ValueError(f"corner include does not uniquely reference {original_pm3.name}")
    return text.replace(original, replacement)


def model_bundle_semantic_identity() -> dict[str, Any]:
    """Describe model semantics without embedding a temporary build path."""
    models: dict[str, Any] = {}
    for model, spec in MODEL_SPECS.items():
        source_pm3 = ROOT / spec["pm3"]
        source_corner = ROOT / spec["corner"]
        patched_pm3_text = patch_pm3(
            source_pm3.read_text(), model, spec["parameters"]
        )
        canonical_corner_text = patch_corner(
            source_corner.read_text(), source_pm3,
            Path(f"<patched_pm3:{model}>")
        )
        models[model] = {
            "parameters": list(spec["parameters"]),
            "source_pm3_sha256": sha256(source_pm3),
            "source_corner_sha256": sha256(source_corner),
            "mismatch_coefficients_sha256": sha256(ROOT / spec["mismatch"]),
            "patched_pm3_semantic_sha256": hashlib.sha256(
                patched_pm3_text.encode()
            ).hexdigest(),
            "patched_corner_semantic_sha256": hashlib.sha256(
                canonical_corner_text.encode()
            ).hexdigest(),
        }
    return {
        "schema_version": 1,
        "method": MODEL_METHOD,
        "limitations": MODEL_LIMITATIONS,
        "lod_parameters_sha256": sha256(ROOT / LOD_PARAMETERS),
        "fixed_model_parameters": FIXED_MODEL_PARAMETERS,
        "models": models,
    }


def build_model_bundle(build: Path) -> tuple[Path, dict[str, Any]]:
    model_dir = build / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, str]] = {}
    include_lines = [
        f'.include "{LOD_PARAMETERS}"',
        ".param sky130_fd_pr__nfet_01v8__dlc_rotweak=0",
        ".param sky130_fd_pr__pfet_01v8__dlc_rotweak=0",
    ]
    for model, spec in MODEL_SPECS.items():
        stem = model.replace("sky130_fd_pr__", "")
        patched_pm3 = model_dir / f"{stem}__tt_mc.pm3.spice"
        patched_corner = model_dir / f"{stem}__tt_mc.corner.spice"
        source_pm3 = ROOT / spec["pm3"]
        source_corner = ROOT / spec["corner"]
        patched_pm3.write_text(
            patch_pm3(source_pm3.read_text(), model, spec["parameters"]),
            encoding="utf-8",
        )
        patched_corner.write_text(
            patch_corner(source_corner.read_text(), source_pm3, patched_pm3),
            encoding="utf-8",
        )
        include_lines.extend((
            f'.include "{relative(patched_corner)}"',
            f'.include "{relative(spec["mismatch"])}"',
        ))
        files[model] = {
            "source_pm3": relative(spec["pm3"]),
            "source_pm3_sha256": sha256(source_pm3),
            "source_corner": relative(spec["corner"]),
            "source_corner_sha256": sha256(source_corner),
            "mismatch_coefficients": relative(spec["mismatch"]),
            "mismatch_coefficients_sha256": sha256(ROOT / spec["mismatch"]),
            "patched_pm3": relative(patched_pm3),
            "patched_pm3_sha256": sha256(patched_pm3),
            "patched_corner": relative(patched_corner),
            "patched_corner_sha256": sha256(patched_corner),
        }
    include = model_dir / "models.inc"
    include.write_text("\n".join(include_lines) + "\n", encoding="utf-8")
    semantic_identity = model_bundle_semantic_identity()
    manifest = {
        "schema_version": 2,
        "method": MODEL_METHOD,
        "limitations": MODEL_LIMITATIONS,
        "include": relative(include),
        "include_sha256": sha256(include),
        "files": files,
        "semantic_identity": semantic_identity,
    }
    manifest["bundle_sha256"] = canonical_sha256(semantic_identity)
    (model_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return include, manifest


def summarize_samples(samples: dict[str, list[float]]) -> dict[str, Any]:
    return {
        name: {
            "count": len(values),
            "mean": statistics.fmean(values),
            "sample_stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "minimum": min(values),
            "maximum": max(values),
        }
        for name, values in sorted(samples.items())
    }


def transform_netlist(text: str, seed: int) -> tuple[str, dict[str, Any]]:
    rng = random.Random(seed)
    counts = {model: 0 for model in MODEL_SPECS}
    samples: dict[str, list[float]] = {
        f"{model}:{name}": []
        for model, spec in MODEL_SPECS.items()
        for name in spec["parameters"]
    }
    output: list[str] = []
    for line in text.splitlines():
        if not line or line[0].upper() != "X":
            output.append(line)
            continue
        tokens = line.split()
        if SPECIAL_NFET in tokens:
            tokens[tokens.index(SPECIAL_NFET)] = "sky130_fd_pr__nfet_01v8"
        models = [model for model in MODEL_SPECS if model in tokens]
        if len(models) != 1:
            output.append(" ".join(tokens))
            continue
        model = models[0]
        counts[model] += 1
        suffix = model.split("__")[-1]
        for name in MODEL_SPECS[model]["parameters"]:
            value = rng.gauss(0.0, 1.0)
            samples[f"{model}:{name}"].append(value)
            tokens.append(f"mc_{suffix}_{name}={value:.17g}")
        output.append(" ".join(tokens))
    transformed = "\n".join(output) + "\n"
    expected = {"sky130_fd_pr__nfet_01v8": 2336, "sky130_fd_pr__pfet_01v8_hvt": 1858}
    if counts != expected:
        raise ValueError(f"extracted MOS population changed: {counts} != {expected}")
    return transformed, {
        "seed": seed,
        "rng": "Python random.Random (MT19937), independent Gaussian draws",
        "device_counts": counts,
        "factor_statistics": summarize_samples(samples),
    }


def replace_model_block(deck: str, model_include: Path) -> str:
    if deck.count(NOMINAL_MODEL_BLOCK) != 1:
        raise ValueError("nominal model include block changed")
    return deck.replace(
        NOMINAL_MODEL_BLOCK, f'.include "{relative(model_include)}"'
    )


def run_case(
    work: Path,
    netlist: Path,
    model_include: Path,
    bundle_hash: str,
    gds: Path,
    view: str,
    incident: int,
    input_peak_v: float,
    timeout: int,
    ngspice: str,
) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    gds_hash = sha256(gds)
    netlist_hash = sha256(netlist)
    deck = replace_model_block(
        deck_text(
            Path(relative(netlist)), netlist_hash, gds_hash,
            beam=0,
            input_phases_deg=codebook_input_phases(incident),
            input_peak_v=input_peak_v,
            distributed_rc=view == "rc",
            operating_point_startup=True,
            analysis_start_us=2.0,
            analysis_stop_us=4.0,
            transient_step_ns=5.0,
            extracted_varactor_model=(
                DEFAULT_VARACTOR_MODEL
                if "sky130_fd_pr__cap_var_lvt" in extracted_model_names(netlist.read_text())
                else None
            ),
        ),
        model_include,
    )
    deck_path = work / "mismatch.spice"
    log_path = work / "ngspice.log"
    report_path = work / "report.json"
    deck_path.write_text(deck, encoding="utf-8")
    runtime = prepare_runtime(work)
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            [ngspice, "-b", "-o", str(log_path.resolve()), str(deck_path.resolve())],
            cwd=runtime,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
    elapsed = time.monotonic() - started
    log = log_path.read_text(errors="replace") if log_path.is_file() else ""
    values = parse_measures(log)
    analysis, errors = analyze(
        values,
        distributed_rc=view == "rc",
        settled_startup=True,
        full_channel_operation=True,
        require_headroom_probes=True,
        require_output=input_peak_v > 0.0 and incident == 0,
        supply_voltage_v=1.8,
    )
    if timed_out:
        errors.append(f"ngspice exceeded the {timeout} second timeout")
    elif returncode:
        errors.append(f"ngspice exited with status {returncode}")
    report = {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "method": "SKY130-coefficient independent MOS mismatch sensitivity pilot",
        "view": view,
        "selected_beam": 0,
        "incident_beam": incident,
        "input_peak_v": input_peak_v,
        "gds": relative(gds),
        "gds_sha256": gds_hash,
        "netlist": relative(netlist),
        "netlist_sha256": netlist_hash,
        "model_include": relative(model_include),
        "model_bundle_sha256": bundle_hash,
        "spiceinit_sha256": hashlib.sha256(SPICE_INIT.encode()).hexdigest(),
        "ngspice": ngspice,
        "ngspice_returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": elapsed,
        "measurements": values,
        "analysis": analysis,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return {"report": relative(report_path), "result": report}


def tone_iq(report: dict[str, Any]) -> tuple[float, float]:
    analysis = report["analysis"]
    return float(analysis["output_tone_i_v"]), float(analysis["output_tone_q_v"])


def evaluate_seed(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    for name in ("constructive", "null", "background"):
        if name not in cases or cases[name]["result"].get("status") != "pass":
            errors.append(f"{name} case is not passing")
    metrics: dict[str, float] = {}
    if not errors:
        wanted_i, wanted_q = tone_iq(cases["constructive"]["result"])
        null_i, null_q = tone_iq(cases["null"]["result"])
        bg_i, bg_q = tone_iq(cases["background"]["result"])
        wanted = math.sqrt(2 * ((wanted_i-bg_i)**2 + (wanted_q-bg_q)**2))
        null = math.sqrt(2 * ((null_i-bg_i)**2 + (null_q-bg_q)**2))
        rejection = math.inf if null == 0 else 20 * math.log10(wanted/null)
        constructive_analysis = cases["constructive"]["result"]["analysis"]
        metrics = {
            "corrected_constructive_rms_v": wanted,
            "corrected_null_rms_v": null,
            "corrected_rejection_db": rejection,
            "output_common_mode_v": constructive_analysis["output_common_mode_v"],
            "minimum_time_aligned_gm_drain_to_tail_v": constructive_analysis[
                "minimum_time_aligned_gm_drain_to_tail_v"
            ],
        }
        if wanted < 0.010:
            errors.append("corrected constructive response is below 10 mV RMS")
        if rejection < 6.0:
            errors.append(f"corrected rejection is below 6 dB: {rejection:.3f}")
        if metrics["output_common_mode_v"] < 0.8:
            errors.append("output common mode is below 0.8 V")
        if metrics["minimum_time_aligned_gm_drain_to_tail_v"] <= 0.0:
            errors.append("GM drain-to-tail margin is non-positive")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "meets_12db_engineering_target": metrics.get("corrected_rejection_db", -math.inf) >= 12.0,
        "metrics": metrics,
        "cases": {name: item["report"] for name, item in sorted(cases.items())},
    }


def frozen_report_identity_errors(
    report: dict[str, Any], *, view: str, incident: int, amplitude: float,
    gds_hash: str, netlist_hash: str, model_bundle_hash: str,
) -> list[str]:
    """Return every reason an existing case cannot enter a frozen aggregate."""
    expected = {
        "view": view,
        "selected_beam": 0,
        "incident_beam": incident,
        "input_peak_v": amplitude,
        "gds_sha256": gds_hash,
        "netlist_sha256": netlist_hash,
        "model_bundle_sha256": model_bundle_hash,
        "spiceinit_sha256": hashlib.sha256(SPICE_INIT.encode()).hexdigest(),
        "ngspice_returncode": 0,
        "timed_out": False,
    }
    return [
        f"{key} differs" for key, value in expected.items()
        if report.get(key) != value
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("base", "rc"), default="base")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seed-count", type=int, default=8)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--base-netlist", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--rc-netlist", type=Path, default=DEFAULT_RC)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--reuse-reports-only",
        action="store_true",
        help=(
            "aggregate existing transform manifests and case reports without "
            "regenerating Python-version-sensitive Gaussian samples"
        ),
    )
    parser.add_argument("--build", type=Path, default=BUILD)
    args = parser.parse_args()
    if args.seed_start < 0 or args.seed_count < 1:
        raise SystemExit("seed range must be nonnegative and nonempty")
    if args.jobs < 1 or args.jobs > 4:
        raise SystemExit("jobs must be between one and four")
    if not shutil.which(args.ngspice):
        raise SystemExit(f"ngspice not found: {args.ngspice}")
    gds = ROOT / args.gds
    nominal = ROOT / (args.base_netlist if args.view == "base" else args.rc_netlist)
    if not gds.is_file() or not nominal.is_file():
        raise SystemExit("frozen GDS or extracted netlist is missing")
    build = ROOT / args.build
    build.mkdir(parents=True, exist_ok=True)
    model_include, model_manifest = build_model_bundle(build)
    seeds: dict[int, dict[str, Any]] = {}
    jobs: list[tuple[int, str, Path, float, int]] = []
    for seed in range(args.seed_start, args.seed_start + args.seed_count):
        seed_dir = build / f"seed_{seed:04d}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        transform_path = seed_dir / "transform.json"
        if args.reuse_reports_only:
            if not transform_path.is_file():
                raise SystemExit(f"seed {seed}: frozen transform manifest is missing")
            transform = json.loads(transform_path.read_text(encoding="utf-8"))
            if transform.get("seed") != seed:
                raise SystemExit(f"seed {seed}: transform seed identity differs")
            if transform.get("source_netlist_sha256") != sha256(nominal):
                raise SystemExit(f"seed {seed}: transform source netlist differs")
            if transform.get("model_bundle_sha256") != model_manifest["bundle_sha256"]:
                raise SystemExit(f"seed {seed}: transform model bundle differs")
            transformed_hash = transform.get("mismatch_netlist_sha256")
            if not isinstance(transformed_hash, str) or len(transformed_hash) != 64:
                raise SystemExit(f"seed {seed}: transformed-netlist hash is missing")
            seeds[seed] = {"transform": transform, "cases": {}}
            for name, incident, amplitude in (
                ("constructive", 0, 0.005),
                ("null", 1, 0.005),
                ("background", 1, 0.0),
            ):
                report_path = seed_dir / name / "report.json"
                if not report_path.is_file():
                    raise SystemExit(f"seed {seed} {name}: frozen report is missing")
                prior = json.loads(report_path.read_text(encoding="utf-8"))
                identity_errors = frozen_report_identity_errors(
                    prior,
                    view=args.view,
                    incident=incident,
                    amplitude=amplitude,
                    gds_hash=sha256(gds),
                    netlist_hash=transformed_hash,
                    model_bundle_hash=model_manifest["bundle_sha256"],
                )
                if identity_errors:
                    raise SystemExit(
                        f"seed {seed} {name}: frozen report identity differs: "
                        + ", ".join(identity_errors)
                    )
                seeds[seed]["cases"][name] = {
                    "report": relative(report_path), "result": prior
                }
                print(f"seed {seed} {name}: frozen {prior.get('status')}", flush=True)
            continue
        transformed, transform = transform_netlist(nominal.read_text(errors="replace"), seed)
        netlist = seed_dir / f"control_final_{args.view}_mc.spice"
        netlist.write_text(transformed, encoding="utf-8")
        transform.update({
            "source_netlist": relative(nominal),
            "source_netlist_sha256": sha256(nominal),
            "mismatch_netlist": relative(netlist),
            "mismatch_netlist_sha256": sha256(netlist),
            "model_bundle_sha256": model_manifest["bundle_sha256"],
        })
        (seed_dir / "transform.json").write_text(
            json.dumps(transform, indent=2, sort_keys=True) + "\n"
        )
        seeds[seed] = {"transform": transform, "cases": {}}
        for name, incident, amplitude in (
            ("constructive", 0, 0.005),
            ("null", 1, 0.005),
            ("background", 1, 0.0),
        ):
            case_dir = seed_dir / name
            report_path = case_dir / "report.json"
            if args.resume and report_path.is_file():
                prior = json.loads(report_path.read_text())
                if (
                    prior.get("gds_sha256") == sha256(gds)
                    and prior.get("netlist_sha256") == sha256(netlist)
                    and prior.get("model_bundle_sha256") == model_manifest["bundle_sha256"]
                ):
                    seeds[seed]["cases"][name] = {
                        "report": relative(report_path), "result": prior
                    }
                    print(f"seed {seed} {name}: reused {prior.get('status')}", flush=True)
                    continue
            jobs.append((seed, name, netlist, amplitude, incident))

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        future_map = {
            pool.submit(
                run_case,
                build / f"seed_{seed:04d}" / name,
                netlist,
                model_include,
                model_manifest["bundle_sha256"],
                gds,
                args.view,
                incident,
                amplitude,
                args.timeout,
                args.ngspice,
            ): (seed, name)
            for seed, name, netlist, amplitude, incident in jobs
        }
        for future in concurrent.futures.as_completed(future_map):
            seed, name = future_map[future]
            item = future.result()
            seeds[seed]["cases"][name] = item
            print(f"seed {seed} {name}: {item['result']['status']}", flush=True)

    seed_reports = {
        str(seed): {
            **evaluate_seed(item["cases"]),
            "transform": relative(build / f"seed_{seed:04d}" / "transform.json"),
            "transform_sha256": sha256(build / f"seed_{seed:04d}" / "transform.json"),
        }
        for seed, item in sorted(seeds.items())
    }
    passing = sum(item["status"] == "pass" for item in seed_reports.values())
    margin = sum(item["meets_12db_engineering_target"] for item in seed_reports.values())
    # When every sampled population passes, p**N = alpha gives the exact
    # one-sided binomial lower confidence bound for the per-seed pass
    # probability p.  This remains scoped to the coefficient model above;
    # it is not a foundry-qualified silicon-yield claim.
    zero_failure_95pct_lower_bound = (
        zero_failure_lower_bound(len(seed_reports))
        if passing == len(seed_reports) else None
    )
    scope_kind = "pilot" if len(seed_reports) < 60 else "campaign"
    model_manifest_path = build / "models" / "manifest.json"
    rebinding_audit_path = build / "bundle_rebinding_audit.json"
    summary = {
        "schema_version": 1,
        "gate": 5,
        "scope": (
            f"{len(seed_reports)}-seed open-PDK coefficient MOS-mismatch "
            f"sensitivity {scope_kind}; not foundry-qualified silicon yield"
        ),
        "status": "pass" if passing == len(seed_reports) else "fail",
        "errors": [] if passing == len(seed_reports) else [
            f"only {passing}/{len(seed_reports)} seeds meet the hard functional gates"
        ],
        "method": model_manifest["method"],
        "aggregation_mode": (
            "frozen_transform_and_report_manifests"
            if args.reuse_reports_only else "generated_in_this_invocation"
        ),
        "limitations": model_manifest["limitations"],
        "view": args.view,
        "gds": relative(gds),
        "gds_sha256": sha256(gds),
        "source_netlist": relative(nominal),
        "source_netlist_sha256": sha256(nominal),
        "model_manifest": relative(model_manifest_path),
        "model_manifest_sha256": sha256(model_manifest_path),
        "model_bundle_sha256": model_manifest["bundle_sha256"],
        "bundle_rebinding_audit": (
            relative(rebinding_audit_path) if rebinding_audit_path.is_file() else None
        ),
        "bundle_rebinding_audit_sha256": (
            sha256(rebinding_audit_path) if rebinding_audit_path.is_file() else None
        ),
        "seed_count": len(seed_reports),
        "passing_seed_count": passing,
        "zero_failure_one_sided_95pct_pass_probability_lower_bound": (
            zero_failure_95pct_lower_bound
        ),
        "seeds_meeting_12db_engineering_target": margin,
        "seeds": seed_reports,
    }
    report_path = build / f"{args.view}_pilot_summary.json"
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"report={relative(report_path)}")
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
