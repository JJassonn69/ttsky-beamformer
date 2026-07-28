#!/usr/bin/env python3
"""Qualify the open-source VACASK analyses needed by the V3 noise gate.

This is deliberately independent of the beamformer deck.  It first checks the
simulator on analytic or internally cross-checked problems:

* driven shooting PSS against the known spectrum of ``0.5 + sin(t)^3``;
* the upstream VACASK HB and HBAC regression decks;
* intrinsic resistor transient noise against ordinary small-signal noise.

The script has no SciPy or plotting dependency so it can run on the validation
server without installing Python packages.  Passing this screen qualifies the
analysis engine only; it does not qualify a SKY130 model or close the V3
periodic-noise gate.
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
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "build/v3/vacask_qualification"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def driven_pss_deck() -> str:
    return r'''Driven PSS analytic qualification

embed "nl3.va" <<<FILE
`include "constants.vams"
`include "disciplines.vams"

module nl3(a, b);
    inout a, b;
    electrical a, b;
    analog I(a, b) <+ 0.5 + pow(V(a, b), 3);
endmodule
>>>FILE

ground 0
load "nl3.va"
model vsource vsource
model nl3 nl3

v1 (1 0) vsource dc=0 type="sine" sinedc=0 ampl=1 freq=1k
nl1 (1 0) nl3

control
  abort always
  options rawfile="binary" strictsave=1
  options pss_tolscale=1e-3
  save default
  analysis pss_driven pss driven=1 tper=1m tstab=10m
endc
'''


def transient_noise_deck(mode: str) -> str:
    return f'''Intrinsic resistor transient-noise qualification ({mode})

ground 0
load "resistor.osdi"
load "capacitor.osdi"

model resistor resistor
model capacitor capacitor
model isource isource

r1 (1 0) resistor r=1k
c1 (1 0) capacitor c=100u
i1 (0 1) isource dc=0

control
  abort always
  options rawfile="binary" strictsave=1
  options reltol=1e-3 vntol=1e-6 abstol=1e-12
  options tran_method="trap"
  options tran_laggednoise=1
  save default
  analysis tran_noise tran stop=200 step=1m noisefmax=100 noisefmin=0.1 \
    oversample=6 noisemode="{mode}" noiseseed=23051984
  analysis ac_noise noise out="1" in="i1" from=0.1 to=100 \
    mode="dec" points=20
endc
'''


def runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{args.vacask_bin.parent}:{env.get('PATH', '')}"
    env["SIM_MODULE_PATH"] = str(args.module_dir)
    env["SIM_INCLUDE_PATH"] = str(args.include_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(args.python_dir), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["SIM_TEST"] = "yes"
    if args.runtime_lib_dir:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(args.runtime_lib_dir), env.get("LD_LIBRARY_PATH", "")]
        ).rstrip(os.pathsep)
    return env


def run_vacask(
    args: argparse.Namespace, deck: Path, case_dir: Path
) -> tuple[str, int]:
    case_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(args.vacask_bin), "-dp", str(deck)],
        cwd=case_dir,
        env=runtime_environment(args),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout,
        check=False,
    )
    log = completed.stdout
    (case_dir / "vacask.log").write_text(log)
    return log, completed.returncode


def load_raw(args: argparse.Namespace, path: Path) -> dict[str, np.ndarray]:
    sys.path.insert(0, str(args.python_dir))
    from rawfile import rawread  # type: ignore[import-not-found]

    return rawread(str(path)).get()


def check_driven_pss(args: argparse.Namespace, build: Path) -> dict[str, Any]:
    case_dir = build / "driven_pss"
    deck = case_dir / "driven_pss.sim"
    write_if_changed(deck, driven_pss_deck())
    log, returncode = run_vacask(args, deck, case_dir)
    raw_path = case_dir / "pss_driven.raw"
    if returncode != 0 or not raw_path.exists():
        raise RuntimeError("VACASK driven PSS failed\n" + "\n".join(log.splitlines()[-40:]))

    data = load_raw(args, raw_path)
    time = np.real(np.asarray(data["time"]))
    current = -np.real(np.asarray(data["v1:flow(br)"]))
    period = float(time[-1] - time[0])
    frequency = 1.0 / period
    endpoint_relative_delta = float(
        abs(current[-1] - current[0]) / max(np.max(np.abs(current)), 1e-30)
    )

    sample_count = 4096
    uniform_time = np.linspace(time[0], time[0] + period, sample_count, endpoint=False)
    uniform_current = np.interp(uniform_time, time, current)
    spectrum = np.fft.rfft(uniform_current) / sample_count
    spectrum[1:-1] *= 2.0
    expected = np.zeros_like(spectrum)
    expected[0] = 0.5
    expected[1] = -0.75j
    expected[3] = 0.25j
    spectrum_max_delta = float(np.max(np.abs(spectrum[:16] - expected[:16])))
    gates = {
        "frequency_within_0p1_percent": abs(frequency / 1000.0 - 1.0) <= 1e-3,
        "endpoint_relative_delta_below_1e_8": endpoint_relative_delta <= 1e-8,
        "analytic_spectrum_delta_below_2e_4": spectrum_max_delta <= 2e-4,
    }
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "gates": gates,
        "frequency_hz": frequency,
        "endpoint_relative_delta": endpoint_relative_delta,
        "spectrum_max_delta_a": spectrum_max_delta,
        "deck_sha256": sha256(deck),
        "raw_sha256": sha256(raw_path),
    }


def parse_array(log: str, label: str) -> list[float]:
    match = re.search(re.escape(label) + r"\s*\[([^]]+)\]", log, re.DOTALL)
    if not match:
        raise RuntimeError(f"missing {label!r} in upstream regression output")
    return [float(value) for value in match.group(1).split()]


def check_upstream_hb(args: argparse.Namespace, build: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    specifications = {
        "hb": args.upstream_test_dir / "test_hb1.sim",
        "hbac": args.upstream_test_dir / "test_hbac1.sim",
    }
    for name, deck in specifications.items():
        case_dir = build / f"upstream_{name}"
        log, returncode = run_vacask(args, deck, case_dir)
        if returncode != 0 or "Error running" in log:
            raise RuntimeError(f"VACASK upstream {name} failed\n" + "\n".join(log.splitlines()[-40:]))
        if name == "hb":
            match = re.search(r"spectrum max delta:\s*([-+0-9.eE]+)", log)
            if not match:
                raise RuntimeError("missing HB spectrum delta")
            maximum_delta = float(match.group(1))
        else:
            values = parse_array(log, "Delta (with hb)") + parse_array(
                log, "Delta (stored hb)"
            )
            maximum_delta = max(abs(value) for value in values)
        gates = {"maximum_delta_below_1e_12": maximum_delta <= 1e-12}
        results[name] = {
            "status": "pass" if all(gates.values()) else "fail",
            "gates": gates,
            "maximum_delta": maximum_delta,
            "upstream_deck": str(deck),
            "upstream_deck_sha256": sha256(deck),
        }
    return results


def check_transient_noise_mode(
    args: argparse.Namespace, build: Path, mode: str
) -> dict[str, Any]:
    case_dir = build / f"transient_noise_{mode}"
    deck = case_dir / "transient_noise.sim"
    write_if_changed(deck, transient_noise_deck(mode))
    log, returncode = run_vacask(args, deck, case_dir)
    transient_path = case_dir / "tran_noise.raw"
    reference_path = case_dir / "ac_noise.raw"
    if returncode != 0 or not transient_path.exists() or not reference_path.exists():
        raise RuntimeError(
            f"VACASK transient noise ({mode}) failed\n"
            + "\n".join(log.splitlines()[-40:])
        )

    transient = load_raw(args, transient_path)
    reference = load_raw(args, reference_path)
    time = np.real(np.asarray(transient["time"]))
    voltage = np.real(np.asarray(transient["1"]))
    frequency = np.real(np.asarray(reference["frequency"]))
    output_psd = np.real(np.asarray(reference["onoise"]))

    measured_variance = float(np.mean(np.square(voltage - np.mean(voltage))))
    reference_variance = float(np.trapezoid(output_psd, frequency))
    ratio_db = 10.0 * math.log10(measured_variance / reference_variance)
    average_timestep = float((time[-1] - time[0]) / max(len(time) - 1, 1))
    required_maximum_timestep = 1.0 / (2.0 * 6.0 * 100.0)
    gates = {
        "at_least_200000_samples": len(time) >= 200_000,
        "average_timestep_within_noise_limit": average_timestep
        <= required_maximum_timestep,
        "integrated_variance_agrees_with_ac_noise_within_3db": abs(ratio_db) <= 3.0,
        "waveform_is_finite": bool(np.all(np.isfinite(voltage))),
    }
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "gates": gates,
        "samples": len(time),
        "average_timestep_s": average_timestep,
        "measured_variance_v2": measured_variance,
        "small_signal_reference_variance_v2": reference_variance,
        "variance_ratio_db": ratio_db,
        "deck_sha256": sha256(deck),
        "transient_raw_sha256": sha256(transient_path),
        "reference_raw_sha256": sha256(reference_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vacask-bin", type=Path, required=True)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--include-dir", type=Path, required=True)
    parser.add_argument("--python-dir", type=Path, required=True)
    parser.add_argument("--runtime-lib-dir", type=Path)
    parser.add_argument("--upstream-test-dir", type=Path, required=True)
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
        args.upstream_test_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    pss = check_driven_pss(args, build)
    upstream = check_upstream_hb(args, build)
    transient_noise = {
        mode: check_transient_noise_mode(args, build, mode)
        for mode in ("zoh", "sde")
    }
    component_statuses = [
        pss["status"],
        upstream["hb"]["status"],
        upstream["hbac"]["status"],
        transient_noise["zoh"]["status"],
        transient_noise["sde"]["status"],
    ]
    report = {
        "status": "pass" if all(value == "pass" for value in component_statuses) else "fail",
        "scope": "VACASK analysis-engine qualification only; not SKY130 or beamformer signoff",
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "vacask_binary": str(args.vacask_bin),
        "vacask_binary_sha256": sha256(args.vacask_bin),
        "driven_pss": pss,
        "upstream": upstream,
        "transient_noise": transient_noise,
        "limitations": [
            "This report does not qualify SKY130 model-card compatibility.",
            "Transient noise is a stochastic cross-check, not native PNoise/HBNoise.",
            "The RC test does not exercise switching or cyclostationary device noise.",
        ],
    }
    report_path = build / "summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
