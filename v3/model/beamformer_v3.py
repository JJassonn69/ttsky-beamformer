#!/usr/bin/env python3
"""Golden constant-gm Cartesian-vector model for beamformer V3A."""

from __future__ import annotations

import argparse
import cmath
from functools import lru_cache
import itertools
import json
import math
from dataclasses import asdict, dataclass
from typing import Sequence


CHANNEL_COUNT = 4
GROUP_WEIGHTS = (1, 2, 4, 8)
TOTAL_UNIT_SLICES = sum(GROUP_WEIGHTS)
AXIS_NAMES = ("I+", "Q+", "I-", "Q-")
AXIS_VECTORS = (1.0 + 0.0j, 0.0 + 1.0j, -1.0 + 0.0j, 0.0 - 1.0j)
PHASE_TABLE_STATES = 8


@dataclass(frozen=True)
class PhaseTableEntry:
    index: int
    target_phase_deg: float
    word: int
    group_codes: tuple[int, ...]
    i_code: int
    q_code: int
    magnitude: float
    phase_deg: float
    phase_error_deg: float


def require_group_codes(group_codes: Sequence[int]) -> tuple[int, ...]:
    codes = tuple(group_codes)
    if len(codes) != len(GROUP_WEIGHTS):
        raise ValueError(f"exactly {len(GROUP_WEIGHTS)} group codes are required")
    if any(code not in range(len(AXIS_VECTORS)) for code in codes):
        raise ValueError("each group code must select I+, Q+, I-, or Q-")
    return codes


def pack_group_codes(group_codes: Sequence[int]) -> int:
    codes = require_group_codes(group_codes)
    return sum(code << (2 * index) for index, code in enumerate(codes))


def unpack_group_codes(word: int) -> tuple[int, ...]:
    if not 0 <= word <= 0xFF:
        raise ValueError("a V3A raw vector word must fit in eight bits")
    return tuple((word >> (2 * index)) & 0x3 for index in range(4))


def vector_from_group_codes(group_codes: Sequence[int]) -> complex:
    codes = require_group_codes(group_codes)
    return sum(
        weight * AXIS_VECTORS[code]
        for weight, code in zip(GROUP_WEIGHTS, codes)
    )


def vector_from_word(word: int) -> complex:
    return vector_from_group_codes(unpack_group_codes(word))


def accounted_unit_slices(word: int) -> int:
    """Return the number of active unit slices represented by a raw word.

    Every legal word steers every group to exactly one axis, so this value is
    invariant.  Keeping the invariant explicit makes accidental future
    introduction of an off state detectable by tests.
    """

    unpack_group_codes(word)
    return TOTAL_UNIT_SLICES


def legacy_phase_word(phase_code: int) -> int:
    if phase_code not in range(4):
        raise ValueError("legacy phase code must be in 0..3")
    return pack_group_codes((phase_code,) * len(GROUP_WEIGHTS))


def phase_deg(value: complex) -> float:
    return math.degrees(cmath.phase(value)) % 360.0


def wrapped_phase_error_deg(actual_deg: float, target_deg: float) -> float:
    return (actual_deg - target_deg + 180.0) % 360.0 - 180.0


@lru_cache(maxsize=1)
def constellation() -> dict[tuple[int, int], int]:
    """Map every integer Cartesian point to its unique raw vector word."""

    points: dict[tuple[int, int], int] = {}
    for group_codes in itertools.product(range(4), repeat=len(GROUP_WEIGHTS)):
        value = vector_from_group_codes(group_codes)
        point = (int(round(value.real)), int(round(value.imag)))
        word = pack_group_codes(group_codes)
        if point in points:
            raise RuntimeError(
                f"constant-gm vector encoding is not unique at {point}: "
                f"0x{points[point]:02x}, 0x{word:02x}"
            )
        points[point] = word
    return points


def magnitude_span_db(entries: Sequence[PhaseTableEntry]) -> float:
    magnitudes = [entry.magnitude for entry in entries]
    return 20.0 * math.log10(max(magnitudes) / min(magnitudes))


def _table_for_radius(state_count: int, radius: float) -> tuple[PhaseTableEntry, ...]:
    points = constellation()
    entries: list[PhaseTableEntry] = []
    for index in range(state_count):
        target_phase = 360.0 * index / state_count
        target = radius * cmath.exp(1j * math.radians(target_phase))
        point, word = min(
            points.items(),
            key=lambda item: (
                abs(complex(*item[0]) - target),
                item[1],
            ),
        )
        value = complex(*point)
        actual_phase = phase_deg(value)
        entries.append(PhaseTableEntry(
            index=index,
            target_phase_deg=target_phase,
            word=word,
            group_codes=unpack_group_codes(word),
            i_code=point[0],
            q_code=point[1],
            magnitude=abs(value),
            phase_deg=actual_phase,
            phase_error_deg=wrapped_phase_error_deg(actual_phase, target_phase),
        ))
    return tuple(entries)


@lru_cache(maxsize=None)
def phase_table(state_count: int = PHASE_TABLE_STATES) -> tuple[PhaseTableEntry, ...]:
    """Select a deterministic near-constant-radius phase lookup table.

    Radius is searched on a fixed 0.05-unit grid.  The ordering of the score
    intentionally prioritizes worst phase error, then magnitude span and RMS
    phase error.  This is architecture quantization, not fitted silicon data.
    """

    if state_count < 4 or state_count % 4:
        raise ValueError("phase table state count must be a multiple of four")
    best: tuple[tuple[float, float, float, float], tuple[PhaseTableEntry, ...]] | None = None
    for radius_index in range(20, TOTAL_UNIT_SLICES * 20 + 1):
        radius = radius_index / 20.0
        entries = _table_for_radius(state_count, radius)
        if len({entry.word for entry in entries}) != state_count:
            continue
        phase_errors = [abs(entry.phase_error_deg) for entry in entries]
        score = (
            max(phase_errors),
            magnitude_span_db(entries),
            math.sqrt(sum(error * error for error in phase_errors) / state_count),
            -sum(entry.magnitude for entry in entries) / state_count,
        )
        if best is None or score < best[0]:
            best = (score, entries)
    if best is None:
        raise RuntimeError(f"could not construct a {state_count}-state phase table")
    return best[1]


def nearest_vector_word(target: complex) -> int:
    """Quantize an arbitrary complex coefficient onto the raw constellation."""

    if abs(target) > TOTAL_UNIT_SLICES + 1e-12:
        raise ValueError(f"target magnitude exceeds full scale {TOTAL_UNIT_SLICES}")
    return min(
        constellation().items(),
        key=lambda item: (abs(complex(*item[0]) - target), item[1]),
    )[1]


def pack_channel_words(channel_words: Sequence[int]) -> int:
    words = tuple(channel_words)
    if len(words) != CHANNEL_COUNT:
        raise ValueError("exactly four channel words are required")
    if any(not 0 <= word <= 0xFF for word in words):
        raise ValueError("each channel word must fit in eight bits")
    return sum(word << (8 * channel) for channel, word in enumerate(words))


def unpack_channel_words(packet: int) -> tuple[int, ...]:
    if not 0 <= packet <= 0xFFFFFFFF:
        raise ValueError("V3A coefficient packet must fit in 32 bits")
    return tuple((packet >> (8 * channel)) & 0xFF for channel in range(4))


def rx_beam_words(
    beam_index: int,
    state_count: int = PHASE_TABLE_STATES,
) -> tuple[int, ...]:
    if not 0 <= beam_index < state_count:
        raise ValueError(f"beam index must be in 0..{state_count - 1}")
    table = phase_table(state_count)
    return tuple(
        table[(-channel * beam_index) % state_count].word
        for channel in range(CHANNEL_COUNT)
    )


def ideal_incident_vector(
    beam_index: int,
    state_count: int = PHASE_TABLE_STATES,
) -> tuple[complex, ...]:
    if not 0 <= beam_index < state_count:
        raise ValueError(f"beam index must be in 0..{state_count - 1}")
    return tuple(
        cmath.exp(1j * math.tau * channel * beam_index / state_count)
        for channel in range(CHANNEL_COUNT)
    )


def normalized_vector(word: int) -> complex:
    value = vector_from_word(word)
    return value / abs(value)


def combine(
    inputs: Sequence[complex],
    channel_words: Sequence[int],
    *,
    normalize_coefficients: bool = True,
) -> complex:
    if len(inputs) != CHANNEL_COUNT or len(channel_words) != CHANNEL_COUNT:
        raise ValueError("exactly four inputs and channel words are required")
    coefficients = (
        tuple(normalized_vector(word) for word in channel_words)
        if normalize_coefficients
        else tuple(vector_from_word(word) / TOTAL_UNIT_SLICES for word in channel_words)
    )
    return sum(sample * coefficient for sample, coefficient in zip(inputs, coefficients))


def beam_response_matrix(
    state_count: int = PHASE_TABLE_STATES,
) -> tuple[tuple[complex, ...], ...]:
    return tuple(
        tuple(
            combine(ideal_incident_vector(incident, state_count), rx_beam_words(selected, state_count))
            for incident in range(state_count)
        )
        for selected in range(state_count)
    )


def array_response(
    angle_deg: float,
    channel_words: Sequence[int],
    *,
    element_spacing_wavelengths: float = 0.5,
    normalize_coefficients: bool = True,
) -> complex:
    if not 0.0 < element_spacing_wavelengths <= 1.0:
        raise ValueError("element spacing must be in (0, 1] wavelengths")
    spatial_phase = math.tau * element_spacing_wavelengths * math.sin(math.radians(angle_deg))
    inputs = tuple(
        cmath.exp(1j * channel * spatial_phase)
        for channel in range(CHANNEL_COUNT)
    )
    return combine(
        inputs,
        channel_words,
        normalize_coefficients=normalize_coefficients,
    )


def phase_table_report(state_count: int = PHASE_TABLE_STATES) -> dict[str, object]:
    entries = phase_table(state_count)
    errors = [abs(entry.phase_error_deg) for entry in entries]
    return {
        "state_count": state_count,
        "worst_phase_error_deg": max(errors),
        "rms_phase_error_deg": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "magnitude_span_db": magnitude_span_db(entries),
        "entries": [asdict(entry) for entry in entries],
    }


def summary() -> dict[str, object]:
    eight = phase_table_report(8)
    sixteen = phase_table_report(16)
    matrix = beam_response_matrix(8)
    return {
        "architecture": "four-channel constant-gm Cartesian vector beamformer",
        "status": "architecture_gate_1_model",
        "signal_plan_hz": {
            "input": 5_000_000,
            "quadrature_lo": 4_000_000,
            "output": 1_000_000,
            "master_clock": 16_000_000,
        },
        "channel_count": CHANNEL_COUNT,
        "group_weights": list(GROUP_WEIGHTS),
        "total_unit_slices_per_channel": TOTAL_UNIT_SLICES,
        "raw_vector_bits_per_channel": 8,
        "raw_vector_points_per_channel": len(constellation()),
        "serial_coefficient_packet_bits": 32,
        "phase_tables": {"guaranteed_8_state": eight, "stretch_16_state": sixteen},
        "eight_beam_response_magnitude": [
            [abs(value) for value in row] for row in matrix
        ],
        "limitations": [
            "ideal coefficient quantization only",
            "not transistor-level or extracted validation",
            "intermediate eight-state beams are not all mutually orthogonal",
            "receive-only low-IF architecture",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("summary", "constellation"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "summary":
        payload = summary()
    else:
        payload = {
            "group_weights": list(GROUP_WEIGHTS),
            "points": [
                {"i": point[0], "q": point[1], "word": word}
                for point, word in sorted(constellation().items())
            ],
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
