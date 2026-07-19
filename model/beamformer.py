#!/usr/bin/env python3
"""Golden narrowband phasor model for the v1 two-channel beamformer."""

from __future__ import annotations

import argparse
import cmath
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AnalogPath:
    resistance_ohm: float = 0.0
    capacitance_f: float = 0.0


@dataclass(frozen=True)
class Channel:
    amplitude_peak_v: float = 0.005
    input_phase_deg: float = 0.0
    lo_phase_deg: float = 0.0
    gain_db: float = 0.0
    path: AnalogPath = AnalogPath()


def db_to_ratio(db: float) -> float:
    return 10.0 ** (db / 20.0)


def ratio_to_db(ratio: float) -> float:
    if ratio <= 0.0:
        return -math.inf
    return 20.0 * math.log10(ratio)


def rc_transfer(frequency_hz: float, path: AnalogPath) -> complex:
    """Return the conservative one-pole transfer of the TT path envelope."""

    omega_rc = (
        2.0
        * math.pi
        * frequency_hz
        * path.resistance_ohm
        * path.capacitance_f
    )
    return 1.0 / complex(1.0, omega_rc)


def channel_if_phasor(channel: Channel, input_frequency_hz: float) -> complex:
    """Return the low-side mixer product phasor for a unit-peak sinusoidal LO."""

    input_phase = math.radians(channel.input_phase_deg)
    lo_phase = math.radians(channel.lo_phase_deg)
    input_phasor = (
        channel.amplitude_peak_v
        * db_to_ratio(channel.gain_db)
        * rc_transfer(input_frequency_hz, channel.path)
        * cmath.exp(1j * input_phase)
    )
    return 0.5 * input_phasor * cmath.exp(-1j * lo_phase)


def beam_phasor(
    channel_1: Channel,
    channel_2: Channel,
    input_frequency_hz: float = 5.0e6,
) -> complex:
    return channel_if_phasor(channel_1, input_frequency_hz) + channel_if_phasor(
        channel_2, input_frequency_hz
    )


def null_depth_db(gain_error_db: float, phase_error_deg: float) -> float:
    """Destructive-to-constructive ratio for two channels with stated errors."""

    ratio = db_to_ratio(gain_error_db)
    phase = math.radians(phase_error_deg)
    constructive = 1.0 + ratio
    residual = abs(1.0 - ratio * cmath.exp(1j * phase))
    if residual == 0.0:
        return math.inf
    return -ratio_to_db(residual / constructive)


def build_summary() -> dict[str, object]:
    maximum_path = AnalogPath(500.0, 5.0e-12)
    nominal_1 = Channel(path=maximum_path)
    nominal_2 = Channel(path=maximum_path)
    constructive = beam_phasor(nominal_1, nominal_2)
    destructive = beam_phasor(
        nominal_1,
        Channel(lo_phase_deg=180.0, path=maximum_path),
    )
    path_h = rc_transfer(5.0e6, maximum_path)
    return {
        "input_frequency_hz": 5.0e6,
        "lo_frequency_hz": 4.0e6,
        "output_frequency_hz": 1.0e6,
        "input_peak_v_per_channel": nominal_1.amplitude_peak_v,
        "maximum_tt_path": asdict(maximum_path),
        "maximum_tt_path_magnitude_db_at_5mhz": ratio_to_db(abs(path_h)),
        "maximum_tt_path_phase_deg_at_5mhz": math.degrees(cmath.phase(path_h)),
        "constructive_output_peak_v": abs(constructive),
        "ideal_destructive_output_peak_v": abs(destructive),
        "ideal_null_depth_db": math.inf,
        "core_error_null_depth_db_0p5db_3deg": null_depth_db(0.5, 3.0),
        "system_error_null_depth_db_1db_8deg": null_depth_db(1.0, 8.0),
    }


def write_summary(output: Path | None) -> None:
    text = json.dumps(build_summary(), indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def write_sweep(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    path = AnalogPath(500.0, 5.0e-12)
    channel_1 = Channel(path=path)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "relative_input_phase_deg",
                "sum_output_peak_v",
                "difference_output_peak_v",
            ),
        )
        writer.writeheader()
        for phase_deg in range(361):
            channel_2_sum = Channel(input_phase_deg=phase_deg, path=path)
            channel_2_difference = Channel(
                input_phase_deg=phase_deg,
                lo_phase_deg=180.0,
                path=path,
            )
            writer.writerow(
                {
                    "relative_input_phase_deg": phase_deg,
                    "sum_output_peak_v": abs(
                        beam_phasor(channel_1, channel_2_sum)
                    ),
                    "difference_output_peak_v": abs(
                        beam_phasor(channel_1, channel_2_difference)
                    ),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="emit key v1 calculations")
    summary.add_argument("--output", type=Path)

    sweep = subparsers.add_parser("sweep", help="write the 0..360 degree sweep")
    sweep.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "summary":
        write_summary(args.output)
    elif args.command == "sweep":
        write_sweep(args.output)


if __name__ == "__main__":
    main()
