#!/usr/bin/env python3
"""Render the V3 periodic-noise evidence as a dependency-free SVG figure."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def attributes(style: dict[str, object]) -> str:
    return " ".join(
        f'{key.rstrip("_").replace("_", "-")}="{value}"'
        for key, value in style.items()
    )


def line(x1: float, y1: float, x2: float, y2: float, **style: object) -> str:
    attrs = attributes(style)
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" {attrs}/>'


def circle(x: float, y: float, radius: float, **style: object) -> str:
    attrs = attributes(style)
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" {attrs}/>'


def text(x: float, y: float, value: object, **style: object) -> str:
    attrs = attributes(style)
    return f'<text x="{x:.2f}" y="{y:.2f}" {attrs}>{html.escape(str(value))}</text>'


def polyline(points: list[tuple[float, float]], **style: object) -> str:
    attrs = attributes(style)
    encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline points="{encoded}" {attrs}/>'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--switched", type=Path,
        default=ROOT / "build/v3/vacask_switched_noise/summary.json",
    )
    parser.add_argument(
        "--scale", type=Path,
        default=ROOT / "build/v3/vacask_noise_scale_linearity/summary.json",
    )
    parser.add_argument(
        "--folding", type=Path,
        default=ROOT / "build/v3/noise_folding_crosscheck/summary.json",
    )
    parser.add_argument(
        "--channel", type=Path,
        default=ROOT / "build/v3/vacask_channel_qualification/summary.json",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "v3/evidence/periodic_noise_summary.svg",
    )
    parser.add_argument(
        "--json-output", type=Path,
        default=ROOT / "v3/evidence/periodic_noise_summary.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = {}
    for name in ("switched", "scale", "folding", "channel"):
        path = getattr(args, name)
        if not path.is_file():
            raise FileNotFoundError(path)
        reports[name] = json.loads(path.read_text())
    if reports["switched"].get("status") not in {
        "pass_pending_frequency_domain_crosscheck", "pass"
    }:
        raise RuntimeError("switched-noise campaign is not passing")
    if reports["scale"].get("status") != "pass":
        raise RuntimeError("scale-linearity qualification is not passing")
    if reports["folding"].get("status") != "pass":
        raise RuntimeError("frequency-domain folding crosscheck is not passing")

    width, height = 1200, 720
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="1200" height="720" fill="#fbfcfe"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.subtitle{font-size:14px;fill:#536076}.axis{font-size:12px;fill:#536076}.panel{font-size:16px;font-weight:650}.value{font-size:13px;font-weight:600}</style>',
        text(48, 42, "V3 switched-noise qualification", class_="title"),
        text(48, 66, "Complete 15-slice channel · 4 MHz quadrature switching · two-pole 2 MHz receiver · TT schematic", class_="subtitle"),
        '<rect x="42" y="90" width="700" height="500" rx="12" fill="#ffffff" stroke="#d9e0ea"/>',
        '<rect x="766" y="90" width="392" height="500" rx="12" fill="#ffffff" stroke="#d9e0ea"/>',
        text(64, 122, "Noise by beam state", class_="panel"),
        text(788, 122, "Noise-amplitude linearity", class_="panel"),
    ]

    switched = reports["switched"]
    mode = switched["configuration"]["primary_mode"]
    by_word = switched["mode_summary"][mode]["by_word"]
    words = [str(word) for word in switched["configuration"]["selected_words"]]
    entries = [by_word[word] for word in words]
    folded_high_uv = (
        reports["folding"]["aggregate"]["mean_folded_noise_v_rms_10khz_to_2mhz"]
        * 1e6
    )
    folded_full_uv = (
        reports["folding"]["aggregate"]["mean_folded_noise_v_rms_10hz_to_2mhz"]
        * 1e6
    )
    values_uv = [
        value * 1e6
        for entry in entries
        for value in (entry["minimum_v"], entry["maximum_v"])
    ] + [folded_high_uv, folded_full_uv]
    ymin = max(0.0, min(values_uv) * 0.82)
    ymax = max(values_uv) * 1.18
    plot_left, plot_right, plot_top, plot_bottom = 84.0, 716.0, 148.0, 515.0

    def state_y(value_uv: float) -> float:
        return plot_bottom - (value_uv - ymin) / (ymax - ymin) * (plot_bottom - plot_top)

    for tick in range(6):
        value = ymin + tick * (ymax - ymin) / 5.0
        y = state_y(value)
        svg.append(line(plot_left, y, plot_right, y, stroke="#edf1f6", stroke_width=1))
        svg.append(text(plot_left - 10, y + 4, f"{value:.1f}", class_="axis", text_anchor="end"))
    svg.append(text(57, 335, "µV RMS", class_="axis", text_anchor="middle", transform="rotate(-90 57 335)"))
    for index, (word, entry) in enumerate(zip(words, entries, strict=True)):
        x = plot_left + (index + 0.5) * (plot_right - plot_left) / len(words)
        low = entry["minimum_v"] * 1e6
        high = entry["maximum_v"] * 1e6
        mean = entry["mean_periodogram_band_rms_v"] * 1e6
        svg.extend((
            line(x, state_y(low), x, state_y(high), stroke="#3269b8", stroke_width=2),
            line(x - 6, state_y(low), x + 6, state_y(low), stroke="#3269b8", stroke_width=2),
            line(x - 6, state_y(high), x + 6, state_y(high), stroke="#3269b8", stroke_width=2),
            circle(x, state_y(mean), 5, fill="#174a8b"),
            text(x, plot_bottom + 23, f"{index * 45}°", class_="axis", text_anchor="middle"),
            text(x, plot_bottom + 41, f"0x{int(word):02X}", class_="axis", text_anchor="middle"),
        ))
    for value, color, label, offset in (
        (folded_high_uv, "#dd7a00", "folded 10 kHz–2 MHz", -8),
        (folded_full_uv, "#9b3f9b", "folded 10 Hz–2 MHz", 16),
    ):
        y = state_y(value)
        svg.append(line(plot_left, y, plot_right, y, stroke=color, stroke_width=2, stroke_dasharray="7 5"))
        svg.append(text(plot_right - 4, y + offset, f"{label}: {value:.1f} µV", class_="value", text_anchor="end", fill=color))

    scale = reports["scale"]
    scales = scale["configuration"]["scales"]
    measured = [
        case["measured_scaled_metrics"]["periodogram_band_rms_v"]
        for case in scale["cases"]
    ]
    slope = scale["fit"]["measured_rms_per_unit_scale_v"]
    sx0, sx1, sy0, sy1 = 806.0, 1126.0, 160.0, 430.0
    log_x0, log_x1 = math.log10(min(scales)), math.log10(max(scales))
    all_y = measured + [slope * min(scales), slope * max(scales)]
    log_y0, log_y1 = math.log10(min(all_y)) - 0.08, math.log10(max(all_y)) + 0.08

    def scale_x(value: float) -> float:
        return sx0 + (math.log10(value) - log_x0) / (log_x1 - log_x0) * (sx1 - sx0)

    def scale_y(value: float) -> float:
        return sy1 - (math.log10(value) - log_y0) / (log_y1 - log_y0) * (sy1 - sy0)

    svg.extend((
        line(sx0, sy1, sx1, sy1, stroke="#778397", stroke_width=1),
        line(sx0, sy0, sx0, sy1, stroke="#778397", stroke_width=1),
        polyline(
            [(scale_x(min(scales)), scale_y(slope * min(scales))), (scale_x(max(scales)), scale_y(slope * max(scales)))],
            fill="none", stroke="#dd7a00", stroke_width=2, stroke_dasharray="7 5",
        ),
    ))
    for x_value, y_value in zip(scales, measured, strict=True):
        x, y = scale_x(x_value), scale_y(y_value)
        svg.extend((
            circle(x, y, 6, fill="#174a8b"),
            text(x, sy1 + 23, f"{x_value:.0e}", class_="axis", text_anchor="middle"),
            text(x + 7, y - 8, f"{y_value * 1e9:.2f} nV", class_="axis"),
        ))
    svg.extend((
        text((sx0 + sx1) / 2, sy1 + 48, "Injected noise amplitude scale", class_="axis", text_anchor="middle"),
        text(780, (sy0 + sy1) / 2, "Measured RMS (log)", class_="axis", text_anchor="middle", transform=f"rotate(-90 780 {(sy0 + sy1) / 2})"),
        text(788, 512, f"R² = {scale['fit']['through_origin_r_squared']:.8f}", class_="value"),
        text(788, 535, f"Extrapolated span = {scale['fit']['extrapolated_noise_span_db']:.3f} dB", class_="value"),
        text(788, 558, f"Production scale = {scale['configuration']['production_scale']:.0e}", class_="value"),
    ))

    channel_tones = [case["vacask"]["tone_peak_v"] for case in reports["channel"]["cases"]]
    worst_state_mean_v = max(
        entry["mean_periodogram_band_rms_v"] for entry in entries
    )
    folded_low_frequency_v = math.sqrt(
        max((folded_full_uv * 1e-6) ** 2 - (folded_high_uv * 1e-6) ** 2, 0.0)
    )
    conservative_noise_v = math.hypot(
        worst_state_mean_v, folded_low_frequency_v
    )
    snr_db = 20.0 * math.log10(
        min(channel_tones) / math.sqrt(2.0) / conservative_noise_v
    )
    comparison = reports["folding"]["comparison_to_switched_transient"]
    algorithm = next(iter(comparison["algorithms"].values()))
    svg.extend((
        '<rect x="42" y="610" width="1116" height="78" rx="10" fill="#eef5ff"/>',
        text(64, 638, f"Independent folding agreement: {algorithm['delta_db']:+.2f} dB (limit ±{comparison['tolerance_db']:.1f} dB)", class_="value"),
        text(64, 663, f"Conservative minimum nominal 5 mV-peak output SNR: {snr_db:.1f} dB · TT schematic only", class_="value"),
        text(595, 638, "Excluded: clock-source phase noise, package/board noise, and extracted-layout parasitics", class_="subtitle"),
        text(595, 663, "Result authorizes V3 floorplanning; it is not fabrication signoff", class_="subtitle"),
        "</svg>",
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(svg) + "\n")
    compact = {
        "schema_version": 1,
        "status": "pass_by_crosschecked_transient_noise_equivalent",
        "scope": "TT schematic complete 15-slice channel; pre-layout only",
        "source_report_sha256": {
            name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
            for name in ("switched", "scale", "folding", "channel")
        },
        "switched_noise": {
            "configuration": switched["configuration"],
            "coverage": switched["coverage"],
            "mode_summary": switched["mode_summary"],
        },
        "noise_scale_linearity": {
            "configuration": scale["configuration"],
            "fit": scale["fit"],
            "gates": scale["gates"],
            "cases": scale["cases"],
        },
        "frequency_domain_crosscheck": {
            "configuration": reports["folding"]["configuration"],
            "relative_parseval_truncation": reports["folding"]["commutator"]["relative_parseval_truncation"],
            "aggregate": reports["folding"]["aggregate"],
            "comparison_to_switched_transient": comparison,
            "gates": reports["folding"]["gates"],
        },
        "conservative_metrics": {
            "minimum_tone_peak_v_at_5mv_input": min(channel_tones),
            "worst_state_mean_v_rms_10khz_to_2mhz": worst_state_mean_v,
            "folded_increment_v_rms_10hz_to_10khz": folded_low_frequency_v,
            "combined_worst_state_mean_v_rms_10hz_to_2mhz": conservative_noise_v,
            "minimum_nominal_output_snr_db_at_5mv_peak": snr_db,
        },
        "limitations": [
            "cross-checked open-source equivalent, not native PNoise",
            "TT schematic only",
            "clock-source phase noise excluded",
            "package and board noise excluded",
            "extracted-layout parasitics excluded",
            "silicon correlation and foundry yield excluded",
        ],
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")
    print(args.output)
    print(args.json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
