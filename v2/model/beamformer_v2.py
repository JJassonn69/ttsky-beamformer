#!/usr/bin/env python3
"""Golden narrowband complex-vector model for the V2 four-channel beamformer."""

from __future__ import annotations

import argparse
import cmath
import json
import math
from dataclasses import dataclass


CHANNEL_COUNT = 4
PHASE_STEPS = 4


@dataclass(frozen=True)
class AnalogPath:
    resistance_ohm: float = 0.0
    capacitance_f: float = 0.0


@dataclass(frozen=True)
class Channel:
    amplitude_peak_v: float = 0.005
    input_phase_deg: float = 0.0
    gain_db: float = 0.0
    trim_code: int = 8
    path: AnalogPath = AnalogPath()


def db_to_ratio(db: float) -> float:
    return 10.0 ** (db / 20.0)


def ratio_to_db(ratio: float) -> float:
    if ratio <= 0.0:
        return -math.inf
    return 20.0 * math.log10(ratio)


def rc_transfer(frequency_hz: float, path: AnalogPath) -> complex:
    omega_rc = (
        2.0
        * math.pi
        * frequency_hz
        * path.resistance_ohm
        * path.capacitance_f
    )
    return 1.0 / complex(1.0, omega_rc)


def trim_scale(code: int, bits: int = 4) -> float:
    """Map the verified equal-unit switched-tail code onto relative current.

    Thirty-six fixed current fingers plus the binary code give 36..51 active
    fingers.  Code 8 activates 44 fingers and is the nominal operating point.
    Small-signal channel gain is provisionally assumed to track tail current;
    the transistor-level channel sweep must quantify any residual curvature.
    """

    maximum_code = (1 << bits) - 1
    if not 0 <= code <= maximum_code:
        raise ValueError(f"trim code must be in 0..{maximum_code}")
    if bits != 4:
        raise ValueError("V2 production trim model is fixed to the verified four-bit bank")
    return (36.0 + code) / 44.0


def tx_phase_codes(beam_index: int) -> tuple[int, ...]:
    if not 0 <= beam_index < PHASE_STEPS:
        raise ValueError("beam index must be in 0..3")
    return tuple((channel_index * beam_index) % PHASE_STEPS for channel_index in range(CHANNEL_COUNT))


def rx_phase_codes(beam_index: int) -> tuple[int, ...]:
    return tuple((-code) % PHASE_STEPS for code in tx_phase_codes(beam_index))


def phase_code_to_phasor(code: int) -> complex:
    if not 0 <= code < PHASE_STEPS:
        raise ValueError("phase code must be in 0..3")
    return cmath.exp(1j * math.tau * code / PHASE_STEPS)


def channel_input_phasor(channel: Channel, input_frequency_hz: float) -> complex:
    return (
        channel.amplitude_peak_v
        * db_to_ratio(channel.gain_db)
        * trim_scale(channel.trim_code)
        * rc_transfer(input_frequency_hz, channel.path)
        * cmath.exp(1j * math.radians(channel.input_phase_deg))
    )


def tx_outputs(
    common_input: complex,
    beam_index: int,
    channel_gains: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
) -> tuple[complex, ...]:
    if len(channel_gains) != CHANNEL_COUNT:
        raise ValueError("exactly four channel gains are required")
    return tuple(
        common_input * channel_gains[index] * phase_code_to_phasor(code)
        for index, code in enumerate(tx_phase_codes(beam_index))
    )


def rx_combined(
    channels: tuple[Channel, ...],
    beam_index: int,
    input_frequency_hz: float = 5.0e6,
    manual_phase_codes: tuple[int, ...] | None = None,
) -> complex:
    if len(channels) != CHANNEL_COUNT:
        raise ValueError("exactly four channels are required")
    phase_codes = manual_phase_codes if manual_phase_codes is not None else rx_phase_codes(beam_index)
    if len(phase_codes) != CHANNEL_COUNT:
        raise ValueError("exactly four phase codes are required")
    return sum(
        channel_input_phasor(channel, input_frequency_hz)
        * phase_code_to_phasor(phase_codes[index])
        for index, channel in enumerate(channels)
    )


def codebook_response_matrix() -> tuple[tuple[complex, ...], ...]:
    rows: list[tuple[complex, ...]] = []
    for selected_beam in range(PHASE_STEPS):
        row: list[complex] = []
        for incident_beam in range(PHASE_STEPS):
            incident = tx_outputs(1.0 + 0.0j, incident_beam)
            channels = tuple(
                Channel(
                    amplitude_peak_v=abs(value),
                    input_phase_deg=math.degrees(cmath.phase(value)),
                )
                for value in incident
            )
            row.append(rx_combined(channels, selected_beam))
        rows.append(tuple(row))
    return tuple(rows)


def build_summary() -> dict[str, object]:
    matrix = codebook_response_matrix()
    return {
        "channel_count": CHANNEL_COUNT,
        "phase_states_deg": [0, 90, 180, 270],
        "input_frequency_hz": 5.0e6,
        "lo_frequency_hz": 4.0e6,
        "master_clock_hz": 16.0e6,
        "output_frequency_hz": 1.0e6,
        "tx_phase_codebook": [list(tx_phase_codes(beam)) for beam in range(4)],
        "rx_phase_codebook": [list(rx_phase_codes(beam)) for beam in range(4)],
        "verified_tail_current_scale_min": trim_scale(0),
        "verified_tail_current_scale_default_code_8": trim_scale(8),
        "verified_tail_current_scale_max": trim_scale(15),
        "ideal_response_magnitude_matrix": [
            [abs(value) for value in row] for row in matrix
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("summary",))
    return parser.parse_args()


def main() -> None:
    parse_args()
    print(json.dumps(build_summary(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
