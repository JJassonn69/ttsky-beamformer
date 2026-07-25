#!/usr/bin/env python3
"""Qualify a VACASK BSIM4 representation against the SKY130 ngspice model.

VACASK does not directly consume ngspice's binned ``.model`` wrappers.  This
tool therefore selects the exact foundry bin used by every V3 MOS geometry,
asks ngspice to evaluate that bin's parameter expressions, and emits a VACASK
BSIM4 4.8.3 candidate using the same evaluated parameters.  Nothing in the
authoritative PDK is edited, and numerical agreement is measured rather than
assumed across this model-version boundary.

The candidate representation is not trusted by construction.  Its DC drain
current, gm, cgs and cgd are compared with ngspice over three drain voltages
and the complete 0--1.8 V gate range.  A representative common-source noise
test is also compared before the model may be used for switched transient
noise.  This is a model-compatibility gate, not beamformer signoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build/v3/vacask_sky130_qualification"
MODEL_CARD = (
    ROOT
    / "third_party/sky130_fd_pr/cells/nfet_01v8"
    / "sky130_fd_pr__nfet_01v8__tt.pm3.spice"
)
MODEL_INCLUDE = ROOT / "spice/sky130/sky130_1v8_tt.inc"
MODEL_BASE = "sky130_fd_pr__nfet_01v8__model"
WRAPPER = "sky130_fd_pr__nfet_01v8"
VDS_VALUES = (0.05, 0.9, 1.8)
VGS_STEP = 0.025

# Every distinct transistor geometry in vector_channel_15.inc and its bias.
GEOMETRIES_UM = {
    "gm": (0.84, 0.60),
    "switch": (0.65, 0.15),
    "tail": (5.066666666, 1.00),
    "bias_reference": (64.0, 1.00),
    "bias_pass": (2.0, 0.15),
    "bias_pulldown": (1.0, 0.15),
}

PARAMETER_RE = re.compile(
    r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\{[^{}]*\}|[^\s]+)"
)
MODEL_START_RE = re.compile(r"^\.model\s+(\S+)\s+(nmos|pmos)\s*$", re.I | re.M)
PRINT_RE = re.compile(
    r"^@[^\n=]+\[([A-Za-z_][A-Za-z0-9_]*)\]\s*=\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$",
    re.MULTILINE,
)
NOISE_TOTAL_RE = re.compile(r"onoise_total\s*=\s*([-+0-9.eE]+)", re.I)


@dataclass(frozen=True)
class ModelBin:
    name: str
    kind: str
    text: str
    raw_parameters: dict[str, str]

    def boundary(self, name: str) -> float:
        return float(self.raw_parameters[name])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def parse_model_bins(path: Path) -> list[ModelBin]:
    text = path.read_text()
    starts = list(MODEL_START_RE.finditer(text))
    bins: list[ModelBin] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        uncommented = " ".join(
            line for line in block.splitlines() if not line.lstrip().startswith("*")
        )
        parameters = {key.lower(): value for key, value in PARAMETER_RE.findall(uncommented)}
        if {"lmin", "lmax", "wmin", "wmax"}.issubset(parameters):
            bins.append(ModelBin(match.group(1), match.group(2).lower(), block, parameters))
    if not bins:
        raise RuntimeError(f"no binned models found in {path}")
    return bins


def select_bin(bins: list[ModelBin], width_um: float, length_um: float) -> ModelBin:
    width = width_um * 1e-6
    length = length_um * 1e-6
    matches = [
        item
        for item in bins
        if item.boundary("lmin") <= length <= item.boundary("lmax")
        and item.boundary("wmin") <= width <= item.boundary("wmax")
    ]
    if not matches:
        raise RuntimeError(f"no model bin for W={width_um} um L={length_um} um")
    # SKY130 deliberately shares boundary values between adjacent bins.  The
    # later declaration is what ngspice selects (confirmed at W/L boundaries).
    return matches[-1]


def runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{args.vacask_bin.parent}:{env.get('PATH', '')}"
    env["SIM_MODULE_PATH"] = str(args.module_dir)
    env["SIM_INCLUDE_PATH"] = str(args.include_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(args.python_dir), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    if args.runtime_lib_dir:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(args.runtime_lib_dir), env.get("LD_LIBRARY_PATH", "")]
        ).rstrip(os.pathsep)
    return env


def run_command(
    command: list[str], cwd: Path, log_path: Path, timeout: int, env: dict[str, str] | None = None
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    log_path.write_text(completed.stdout)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            + "\n".join(completed.stdout.splitlines()[-60:])
        )
    return completed.stdout


def model_parameter_names(model_bin: ModelBin) -> list[str]:
    excluded = {"level", "version", "lmin", "lmax", "wmin", "wmax"}
    return [name for name in model_bin.raw_parameters if name not in excluded]


def ngspice_parameter_probe_deck(
    label: str,
    width_um: float,
    length_um: float,
    model_bin: ModelBin,
    query_names: list[str],
) -> str:
    queries = "\n".join(
        f"print @xprobe:{model_bin.name}[{name}]"
        for name in query_names
    )
    return f"""* Evaluate SKY130 model expressions for {label}.
.option scale=1e-6
.include \"{MODEL_INCLUDE}\"
VDS d 0 0.9
VGS g 0 0.9
XPROBE d g 0 0 {WRAPPER} w={width_um:.12g} l={length_um:.12g}
.control
set numdgt=16
set width=240
op
{queries}
quit
.endc
.end
"""


def evaluated_parameters(
    args: argparse.Namespace,
    case_dir: Path,
    label: str,
    width_um: float,
    length_um: float,
    model_bin: ModelBin,
) -> tuple[dict[str, float], list[str]]:
    deck = case_dir / "parameter_probe.spice"
    values: dict[str, float] = {}
    literal_parameters: list[str] = []
    expression_parameters: list[str] = []
    for name in model_parameter_names(model_bin):
        try:
            values[name] = float(model_bin.raw_parameters[name])
            literal_parameters.append(name)
        except ValueError:
            expression_parameters.append(name)
    write_if_changed(
        deck,
        ngspice_parameter_probe_deck(
            label, width_um, length_um, model_bin, expression_parameters
        ),
    )
    log = run_command(
        [str(args.ngspice), "-b", str(deck)], ROOT, case_dir / "parameter_probe.log", args.timeout
    )
    values.update(
        {name.lower(): float(value) for name, value in PRINT_RE.findall(log)}
    )
    missing = sorted(set(expression_parameters) - values.keys())
    if missing:
        raise RuntimeError(f"ngspice did not expose {len(missing)} parameters: {missing}")
    return values, literal_parameters


def vacask_model_text(name: str, values: dict[str, float]) -> str:
    lines = [f"model {name} sp_bsim4v8 (", "  type=1", '  version="4.8.3"']
    for parameter in sorted(values):
        value = values[parameter]
        if not math.isfinite(value):
            raise RuntimeError(f"non-finite model parameter {parameter}={value}")
        lines.append(f"  {parameter}=({value:.16g})")
    lines.append(")")
    return "\n".join(lines) + "\n"


def ngspice_dc_deck(
    width_um: float, length_um: float, vds: float, output_path: Path
) -> str:
    device = "m.xdev.msky130_fd_pr__nfet_01v8"
    return f"""* SKY130 ngspice DC reference.
.option scale=1e-6
.include \"{MODEL_INCLUDE}\"
VDS d 0 {vds:.12g}
VGS g 0 0
XDEV d g 0 0 {WRAPPER} w={width_um:.12g} l={length_um:.12g}
.control
set wr_vecnames
set wr_singlescale
set numdgt=16
save v(g) i(VDS) @{device}[gm] @{device}[cgs] @{device}[cgd]
dc VGS 0 1.8 {VGS_STEP}
wrdata {output_path} v(g) i(VDS) @{device}[gm] @{device}[cgs] @{device}[cgd]
quit
.endc
.end
"""


def vacask_dc_deck(
    width_um: float, length_um: float, vds: float, model_text: str
) -> str:
    return f"""SKY130 VACASK DC candidate

ground 0
load "spice/bsim4v8.osdi"
{model_text}
model vsource vsource
vds (d 0) vsource dc={vds:.12g}
vgs (g 0) vsource dc=0
m1 (d g 0 0) candidate w={width_um * 1e-6:.16g} l={length_um * 1e-6:.16g} nf=1

control
  abort always
  options rawfile="binary" strictsave=1
  save p(m1,gm) p(m1,cgs) p(m1,cgd) default
  sweep vgs instance="vgs" parameter="dc" from=0 to=1.8 step={VGS_STEP}
    analysis op op
endc
"""


def load_ngspice_dc(path: Path) -> dict[str, np.ndarray]:
    data = np.loadtxt(path, skiprows=1)
    if data.ndim != 2 or data.shape[1] != 6:
        raise RuntimeError(f"unexpected ngspice wrdata shape {data.shape} in {path}")
    return {
        "vgs": data[:, 1],
        "id": -data[:, 2],
        "gm": data[:, 3],
        "cgs": np.abs(data[:, 4]),
        "cgd": np.abs(data[:, 5]),
    }


def load_vacask_raw(args: argparse.Namespace, path: Path) -> dict[str, np.ndarray]:
    sys.path.insert(0, str(args.python_dir))
    from rawfile import rawread  # type: ignore[import-not-found]

    raw = rawread(str(path)).get()
    return {key.lower(): np.real(np.asarray(raw[key])) for key in raw.names}


def aligned_vacask_dc(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    def get(*names: str) -> np.ndarray:
        for name in names:
            if name in raw:
                return raw[name]
        raise RuntimeError(f"none of {names} found; raw keys={sorted(raw)}")

    return {
        "vgs": get("g", "vgs.dc"),
        "id": -get("vds:flow(br)", "vds.flow(br)"),
        "gm": get("m1.gm"),
        "cgs": np.abs(get("m1.cgs")),
        "cgd": np.abs(get("m1.cgd")),
    }


def error_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    difference = candidate - reference
    scale = max(float(np.max(np.abs(reference))), 1e-30)
    active = np.abs(reference) >= max(scale * 1e-4, 1e-18)
    relative = np.abs(difference[active]) / np.maximum(np.abs(reference[active]), scale * 1e-4)
    return {
        "normalized_rmse_percent": 100.0 * float(np.sqrt(np.mean(difference**2))) / scale,
        "maximum_active_relative_percent": 100.0 * float(np.max(relative)) if np.any(active) else 0.0,
        "maximum_absolute": float(np.max(np.abs(difference))),
    }


def compare_dc_case(
    args: argparse.Namespace,
    case_dir: Path,
    width_um: float,
    length_um: float,
    vds: float,
    model_text: str,
) -> dict[str, Any]:
    reference_path = case_dir / "ngspice_dc.dat"
    ng_deck = case_dir / "ngspice_dc.spice"
    vc_deck = case_dir / "vacask_dc.sim"
    write_if_changed(ng_deck, ngspice_dc_deck(width_um, length_um, vds, reference_path))
    write_if_changed(vc_deck, vacask_dc_deck(width_um, length_um, vds, model_text))
    run_command([str(args.ngspice), "-b", str(ng_deck)], ROOT, case_dir / "ngspice_dc.log", args.timeout)
    run_command(
        [str(args.vacask_bin), "-dp", str(vc_deck)],
        case_dir,
        case_dir / "vacask_dc.log",
        args.timeout,
        runtime_environment(args),
    )
    reference = load_ngspice_dc(reference_path)
    candidate = aligned_vacask_dc(load_vacask_raw(args, case_dir / "op.raw"))
    if len(reference["vgs"]) != len(candidate["vgs"]) or not np.allclose(
        reference["vgs"], candidate["vgs"], rtol=0, atol=1e-10
    ):
        raise RuntimeError("ngspice and VACASK VGS grids do not align")
    # VACASK's SPICE-derived module exposes an internal ``gm`` quantity that
    # is not the terminal d(Id)/d(Vg), despite the familiar name.  Derive gm
    # independently from each simulator's terminal current curve instead.
    reference["gm"] = np.gradient(reference["id"], reference["vgs"], edge_order=2)
    candidate["gm"] = np.gradient(candidate["id"], candidate["vgs"], edge_order=2)
    metrics = {
        quantity: error_metrics(reference[quantity], candidate[quantity])
        for quantity in ("id", "gm", "cgs", "cgd")
    }
    gates = {
        "id_normalized_rmse_at_most_2_percent": metrics["id"]["normalized_rmse_percent"] <= 2.0,
        "gm_normalized_rmse_at_most_3_percent": metrics["gm"]["normalized_rmse_percent"] <= 3.0,
        "cgs_normalized_rmse_at_most_10_percent": metrics["cgs"]["normalized_rmse_percent"] <= 10.0,
        "cgd_normalized_rmse_at_most_10_percent": metrics["cgd"]["normalized_rmse_percent"] <= 10.0,
        "all_values_finite": all(np.all(np.isfinite(value)) for value in candidate.values()),
    }
    bias_index = int(np.argmin(np.abs(reference["vgs"] - 0.9)))
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "vds_v": vds,
        "sample_count": len(reference["vgs"]),
        "gm_measurement": "second-order numerical d(Id)/d(Vgs) from terminal current",
        "bias_point_at_0p9v": {
            "ngspice_id_a": float(reference["id"][bias_index]),
            "vacask_id_a": float(candidate["id"][bias_index]),
        },
        "metrics": metrics,
        "gates": gates,
        "ngspice_deck_sha256": sha256(ng_deck),
        "vacask_deck_sha256": sha256(vc_deck),
    }


def ngspice_noise_deck(
    width_um: float,
    length_um: float,
    load_ohm: float,
    spectrum_path: Path,
) -> str:
    return f"""* SKY130 ngspice stationary-noise reference.
.option scale=1e-6
.include \"{MODEL_INCLUDE}\"
VDD vdd 0 1.8
VGS g 0 dc 0.9 ac 1
RLOAD vdd d {load_ohm:.16g}
XDEV d g 0 0 {WRAPPER} w={width_um:.12g} l={length_um:.12g}
.noise v(d) VGS dec 20 10 2meg 1
.control
run
set wr_vecnames
set wr_singlescale
set numdgt=16
setplot noise1
wrdata {spectrum_path} onoise_spectrum
setplot noise2
print onoise_total
quit
.endc
.end
"""


def vacask_noise_deck(
    width_um: float, length_um: float, load_ohm: float, model_text: str
) -> str:
    return f"""SKY130 VACASK stationary-noise candidate

ground 0
load "spice/bsim4v8.osdi"
load "resistor.osdi"
{model_text}
model resistor resistor
model vsource vsource
vdd (vdd 0) vsource dc=1.8
vgs (g 0) vsource dc=0.9
rload (vdd d) resistor r={load_ohm:.16g}
m1 (d g 0 0) candidate w={width_um * 1e-6:.16g} l={length_um * 1e-6:.16g} nf=1

control
  abort always
  options rawfile="binary" strictsave=1
  save default
  analysis stationary_noise noise out="d" in="vgs" from=10 to=2meg mode="dec" points=20
endc
"""


def compare_stationary_noise(
    args: argparse.Namespace,
    case_dir: Path,
    width_um: float,
    length_um: float,
    model_text: str,
    drain_current_a: float,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    if drain_current_a <= 0:
        raise RuntimeError(f"invalid drain current for noise load: {drain_current_a}")
    load_ohm = 0.9 / drain_current_a
    spectrum_path = case_dir / "ngspice_noise.dat"
    ng_deck = case_dir / "ngspice_noise.spice"
    vc_deck = case_dir / "vacask_noise.sim"
    write_if_changed(
        ng_deck,
        ngspice_noise_deck(width_um, length_um, load_ohm, spectrum_path),
    )
    write_if_changed(
        vc_deck,
        vacask_noise_deck(width_um, length_um, load_ohm, model_text),
    )
    ng_log = run_command(
        [str(args.ngspice), "-b", str(ng_deck)],
        ROOT,
        case_dir / "ngspice_noise.log",
        args.timeout,
    )
    run_command(
        [str(args.vacask_bin), "-dp", str(vc_deck)],
        case_dir,
        case_dir / "vacask_noise.log",
        args.timeout,
        runtime_environment(args),
    )
    ng_data = np.loadtxt(spectrum_path, skiprows=1)
    if ng_data.ndim != 2 or ng_data.shape[1] != 2:
        raise RuntimeError(f"unexpected ngspice noise shape {ng_data.shape}")
    ng_frequency = ng_data[:, 0]
    ng_psd = np.square(ng_data[:, 1])
    vc_raw = load_vacask_raw(args, case_dir / "stationary_noise.raw")
    vc_frequency = vc_raw["frequency"]
    vc_psd = vc_raw["onoise"]
    if len(ng_frequency) != len(vc_frequency) or not np.allclose(
        ng_frequency, vc_frequency, rtol=1e-8, atol=1e-12
    ):
        vc_psd = np.interp(np.log(ng_frequency), np.log(vc_frequency), vc_psd)
        vc_frequency = ng_frequency
    ng_variance = float(np.trapezoid(ng_psd, ng_frequency))
    vc_variance = float(np.trapezoid(vc_psd, vc_frequency))
    ratio_db = 10.0 * math.log10(vc_variance / ng_variance)
    point_delta_db = 10.0 * np.log10(vc_psd / ng_psd)
    total_match = NOISE_TOTAL_RE.search(ng_log)
    if not total_match:
        raise RuntimeError("ngspice did not report onoise_total")
    ng_reported_rms = float(total_match.group(1))
    integration_delta_percent = 100.0 * (
        math.sqrt(ng_variance) / ng_reported_rms - 1.0
    )
    gates = {
        "integrated_noise_within_3db": abs(ratio_db) <= 3.0,
        "spectral_95th_percentile_within_3db": float(
            np.percentile(np.abs(point_delta_db), 95)
        )
        <= 3.0,
        "ngspice_spectrum_integrates_within_1_percent_of_reported_total": abs(
            integration_delta_percent
        )
        <= 1.0,
        "all_values_positive_and_finite": bool(
            np.all(np.isfinite(ng_psd))
            and np.all(np.isfinite(vc_psd))
            and np.all(ng_psd > 0)
            and np.all(vc_psd > 0)
        ),
    }
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "vgs_v": 0.9,
        "target_vds_v": 0.9,
        "load_ohm": load_ohm,
        "frequency_range_hz": [float(ng_frequency[0]), float(ng_frequency[-1])],
        "frequency_points": len(ng_frequency),
        "ngspice_integrated_output_noise_v_rms": math.sqrt(ng_variance),
        "ngspice_reported_output_noise_v_rms": ng_reported_rms,
        "ngspice_integration_delta_percent": integration_delta_percent,
        "vacask_integrated_output_noise_v_rms": math.sqrt(vc_variance),
        "vacask_to_ngspice_integrated_noise_db": ratio_db,
        "spectral_absolute_delta_db": {
            "median": float(np.median(np.abs(point_delta_db))),
            "p95": float(np.percentile(np.abs(point_delta_db), 95)),
            "maximum": float(np.max(np.abs(point_delta_db))),
        },
        "gates": gates,
        "ngspice_deck_sha256": sha256(ng_deck),
        "vacask_deck_sha256": sha256(vc_deck),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vacask-bin", type=Path, required=True)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--include-dir", type=Path, required=True)
    parser.add_argument("--python-dir", type=Path, required=True)
    parser.add_argument("--runtime-lib-dir", type=Path)
    parser.add_argument("--ngspice", type=Path, default=Path("/usr/bin/ngspice"))
    parser.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    for path in (
        args.vacask_bin,
        args.module_dir,
        args.include_dir,
        args.python_dir,
        args.ngspice,
        MODEL_CARD,
        MODEL_INCLUDE,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    bins = parse_model_bins(MODEL_CARD)
    geometry_reports: dict[str, Any] = {}
    statuses: list[str] = []
    for label, (width_um, length_um) in GEOMETRIES_UM.items():
        geometry_dir = build / label
        geometry_dir.mkdir(parents=True, exist_ok=True)
        model_bin = select_bin(bins, width_um, length_um)
        values, literal_parameters = evaluated_parameters(
            args, geometry_dir, label, width_um, length_um, model_bin
        )
        model_text = vacask_model_text("candidate", values)
        model_path = geometry_dir / "vacask_model.inc"
        write_if_changed(model_path, model_text)
        dc = [
            compare_dc_case(
                args,
                geometry_dir / f"vds_{str(vds).replace('.', 'p')}",
                width_um,
                length_um,
                vds,
                model_text,
            )
            for vds in VDS_VALUES
        ]
        stationary_noise = compare_stationary_noise(
            args,
            geometry_dir / "stationary_noise",
            width_um,
            length_um,
            model_text,
            dc[1]["bias_point_at_0p9v"]["ngspice_id_a"],
        )
        status = (
            "pass"
            if all(item["status"] == "pass" for item in dc)
            and stationary_noise["status"] == "pass"
            else "fail"
        )
        statuses.append(status)
        geometry_reports[label] = {
            "status": status,
            "width_um": width_um,
            "length_um": length_um,
            "selected_foundry_bin": model_bin.name,
            "foundry_bin_bounds_m": {
                key: model_bin.boundary(key) for key in ("lmin", "lmax", "wmin", "wmax")
            },
            "evaluated_parameter_count": len(values),
            "literal_parameters_copied_directly": len(literal_parameters),
            "expression_parameters_evaluated_by_ngspice": len(values)
            - len(literal_parameters),
            "vacask_model_sha256": sha256(model_path),
            "dc": dc,
            "stationary_noise": stationary_noise,
        }

    report = {
        "schema_version": 1,
        "status": "pass" if all(status == "pass" for status in statuses) else "fail",
        "scope": "SKY130-to-VACASK exact-V3-geometry DC, capacitance and stationary-noise compatibility; not periodic-noise or beamformer signoff",
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "ngspice": str(args.ngspice),
        "vacask_binary": str(args.vacask_bin),
        "vacask_binary_sha256": sha256(args.vacask_bin),
        "vacask_bsim4_osdi": "spice/bsim4v8.osdi",
        "vacask_bsim4_osdi_sha256": sha256(args.module_dir / "spice/bsim4v8.osdi"),
        "foundry_model_card": str(MODEL_CARD.relative_to(ROOT)),
        "foundry_model_card_sha256": sha256(MODEL_CARD),
        "foundry_include": str(MODEL_INCLUDE.relative_to(ROOT)),
        "foundry_include_sha256": sha256(MODEL_INCLUDE),
        "translation": {
            "method": "ngspice-evaluated exact bin parameters copied into VACASK's SPICE-derived BSIM4 4.8.3 candidate",
            "authoritative_pdk_modified": False,
            "boundary_rule": "last matching SKY130 declaration, matching ngspice at shared W/L boundaries",
        },
        "geometries": geometry_reports,
        "limitations": [
            "This model-compatibility report checks DC current, gm, terminal capacitances and stationary noise.",
            "Switched transient noise and beamformer-level noise folding remain separate gates.",
            "SKY130 specifies BSIM4 4.5 while VACASK's SPICE-derived core supports 4.8.x; measured equivalence is required rather than assumed.",
        ],
    }
    summary = build / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
