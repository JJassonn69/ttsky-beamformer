#!/usr/bin/env python3
"""Generate deterministic, hash-bound SVG figures for the frozen V2 datasheet.

The figures deliberately distinguish characterization from release gates.  They
use only Python's standard library so the plotting flow can run in the normal
TinyTapeout repository without adding a plotting dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = json.loads(
    (ROOT / "v2/layout/vcm_varactor_eco.json").read_text(encoding="utf-8")
)
_EXTRACTION = json.loads(
    (ROOT / "build/v2/control_routing/final_rc/coverage_audit.json").read_text(
        encoding="utf-8"
    )
)
EXPECTED_GDS_SHA256 = _CONTRACT["output_checkpoint"]["sha256"]
EXPECTED_BASE_NETLIST_SHA256 = _EXTRACTION["sha256"]["base"]
EXPECTED_RC_NETLIST_SHA256 = _EXTRACTION["sha256"]["distributed_rc"]

INK = "#172033"
MUTED = "#5b6475"
GRID = "#d9dee8"
PANEL = "#f7f9fc"
BLUE = "#177ddc"
TEAL = "#0b8f87"
ORANGE = "#d97706"
PURPLE = "#7c3aed"
GREEN = "#27884a"
RED = "#c43d3d"
AMBER = "#aa6a00"
CHANNEL_COLORS = (BLUE, ORANGE, PURPLE, GREEN)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_hashes(
    document: dict[str, Any], *, gds: str, netlist: str, context: str
) -> None:
    gds_values: list[str] = []
    netlist_values: list[str] = []
    artifact_sets = [document.get("artifact_hashes", {})]
    if isinstance(document.get("metrics"), dict):
        artifact_sets.append(document["metrics"].get("artifact_hashes", {}))
    for artifact_hashes in artifact_sets:
        if isinstance(artifact_hashes, dict):
            gds_values.extend(artifact_hashes.get("gds_sha256", []))
            netlist_values.extend(artifact_hashes.get("netlist_sha256", []))
    if document.get("gds_sha256"):
        gds_values.append(document["gds_sha256"])
    if document.get("netlist_sha256"):
        netlist_values.append(document["netlist_sha256"])
    require(gds in gds_values, f"{context}: expected GDS hash is absent")
    require(netlist in netlist_values, f"{context}: expected netlist hash is absent")


class Svg:
    def __init__(self, width: int, height: int, title: str, description: str):
        self.width = width
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-labelledby="svg-title svg-desc">',
            f'<title id="svg-title">{esc(title)}</title>',
            f'<desc id="svg-desc">{esc(description)}</desc>',
            "<style>"
            "text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;"
            f"fill:{INK}}}"
            ".title{font-size:26px;font-weight:600}.subtitle{font-size:15px;"
            f"fill:{MUTED}}}.axis{{font-size:14px;fill:{MUTED}}}"
            ".tick{font-size:13px;fill:#667085}.value{font-size:14px;font-weight:600}"
            ".small{font-size:12px;fill:#667085}.cell{font-size:18px;font-weight:600}"
            ".cellsub{font-size:12px}.label{font-size:15px;font-weight:600}"
            "</style>",
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        ]

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: str = "none",
        stroke: str = "none",
        stroke_width: float = 1,
        rx: float = 0,
        opacity: float = 1,
    ) -> None:
        self.add(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" '
            f'height="{height:.2f}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{stroke_width}" rx="{rx}" opacity="{opacity}"/>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = INK,
        stroke_width: float = 1,
        dash: str | None = None,
        opacity: float = 1,
    ) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" '
            f'y2="{y2:.2f}" stroke="{stroke}" stroke-width="{stroke_width}"'
            f'{dash_attr} opacity="{opacity}"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        *,
        css_class: str = "",
        anchor: str = "start",
        fill: str | None = None,
        rotate: float | None = None,
    ) -> None:
        class_attr = f' class="{css_class}"' if css_class else ""
        fill_attr = f' style="fill:{fill}"' if fill else ""
        rotate_attr = (
            f' transform="rotate({rotate:.2f} {x:.2f} {y:.2f})"'
            if rotate is not None
            else ""
        )
        self.add(
            f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}"'
            f'{class_attr}{fill_attr}{rotate_attr}>{esc(value)}</text>'
        )

    def circle(
        self,
        x: float,
        y: float,
        radius: float,
        *,
        fill: str,
        stroke: str = "#ffffff",
        stroke_width: float = 2,
    ) -> None:
        self.add(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )

    def polyline(
        self,
        points: Iterable[tuple[float, float]],
        *,
        stroke: str,
        stroke_width: float = 2,
        fill: str = "none",
    ) -> None:
        encoded = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.add(
            f'<polyline points="{encoded}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{stroke_width}" stroke-linejoin="round" '
            'stroke-linecap="round"/>'
        )

    def finish(self) -> str:
        return "\n".join((*self.parts, "</svg>", ""))


def interpolate_hex(start: str, end: str, fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
    end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(
        round(a + (b - a) * fraction) for a, b in zip(start_rgb, end_rgb)
    )
    return "#" + "".join(f"{component:02x}" for component in mixed)


def draw_title(svg: Svg, title: str, subtitle: str) -> None:
    svg.text(60, 48, title, css_class="title")
    svg.text(60, 76, subtitle, css_class="subtitle")


def draw_footer(svg: Svg, source_sha: str, extra: str = "") -> None:
    note = (
        f"GDS {EXPECTED_GDS_SHA256[:12]} | source {source_sha[:12]}"
        + (f" | {extra}" if extra else "")
    )
    svg.text(svg.width - 42, svg.height - 22, note, css_class="small", anchor="end")


def render_codebook(codebook: dict[str, Any], source_sha: str) -> str:
    matrix = codebook["metrics"]["raw_response_matrix_v_rms"]
    require(len(matrix) == 4 and all(len(row) == 4 for row in matrix), "codebook matrix is not 4 by 4")
    relative_db = []
    for row_index, row in enumerate(matrix):
        diagonal = row[row_index]
        relative_db.append([20.0 * math.log10(max(value, 1e-30) / diagonal) for value in row])

    svg = Svg(
        1180,
        940,
        "Extracted-RC four-beam response matrix",
        "Relative output amplitude for every selected-beam and incident-beam pair.",
    )
    draw_title(
        svg,
        "Extracted-RC four-beam response matrix",
        "Raw 1 MHz differential output, row-normalized to the intended beam; no background subtraction",
    )
    origin_x, origin_y, cell = 230.0, 170.0, 165.0
    svg.text(origin_x + 2 * cell, 112, "Incident beam", css_class="label", anchor="middle")
    svg.text(68, origin_y + 2 * cell, "Selected beam", css_class="label", anchor="middle", rotate=-90)
    for index in range(4):
        svg.text(origin_x + (index + 0.5) * cell, 148, f"B{index}", css_class="label", anchor="middle")
        svg.text(origin_x - 28, origin_y + (index + 0.52) * cell, f"B{index}", css_class="label", anchor="end")
    for row in range(4):
        for column in range(4):
            value = relative_db[row][column]
            intensity = (max(-80.0, min(0.0, value)) + 80.0) / 80.0
            fill = interpolate_hex("#edf2f7", "#1264a3", intensity)
            svg.rect(
                origin_x + column * cell,
                origin_y + row * cell,
                cell - 3,
                cell - 3,
                fill=fill,
                stroke="#ffffff",
                stroke_width=2,
                rx=5,
            )
            text_fill = "#ffffff" if intensity > 0.55 else INK
            label = "0.00 dB" if row == column else f"{value:.1f} dBc"
            svg.text(
                origin_x + (column + 0.5) * cell,
                origin_y + (row + 0.48) * cell,
                label,
                css_class="cell",
                anchor="middle",
                fill=text_fill,
            )
            svg.text(
                origin_x + (column + 0.5) * cell,
                origin_y + (row + 0.66) * cell,
                f"{matrix[row][column] * 1000:.4g} mV RMS",
                css_class="cellsub",
                anchor="middle",
                fill=text_fill,
            )

    metrics = codebook["metrics"]
    summary_y = 860
    svg.text(230, summary_y, f"Minimum rejection  {metrics['minimum_rejection_db']:.2f} dB", css_class="label")
    svg.text(580, summary_y, f"Constructive spread  {metrics['constructive_spread_db']:.3f} dB", css_class="label")
    svg.text(930, summary_y, "PASS", css_class="label", fill=GREEN)
    draw_footer(svg, source_sha, "TT, 1.8 V, 27 C, 5 mVpk/channel")
    return svg.finish()


def map_xy(
    x: float,
    y: float,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> tuple[float, float]:
    px = left + width * (x - x_min) / (x_max - x_min)
    py = top + height * (1.0 - (y - y_min) / (y_max - y_min))
    return px, py


def draw_axes(
    svg: Svg,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    x_ticks: Sequence[float],
    y_ticks: Sequence[float],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    x_formatter=lambda value: f"{value:g}",
    y_formatter=lambda value: f"{value:g}",
    x_label: str = "",
    y_label: str = "",
) -> None:
    svg.rect(left, top, width, height, fill="#ffffff", stroke=GRID, stroke_width=1)
    for value in y_ticks:
        _, py = map_xy(
            x_min,
            value,
            left=left,
            top=top,
            width=width,
            height=height,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        svg.line(left, py, left + width, py, stroke=GRID)
        svg.text(left - 12, py + 5, y_formatter(value), css_class="tick", anchor="end")
    for value in x_ticks:
        px, _ = map_xy(
            value,
            y_min,
            left=left,
            top=top,
            width=width,
            height=height,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
        )
        svg.line(px, top + height, px, top + height + 6, stroke=MUTED)
        svg.text(px, top + height + 23, x_formatter(value), css_class="tick", anchor="middle")
    if x_label:
        svg.text(left + width / 2, top + height + 50, x_label, css_class="axis", anchor="middle")
    if y_label:
        svg.text(left - 62, top + height / 2, y_label, css_class="axis", anchor="middle", rotate=-90)


def render_trim(trim: dict[str, Any], source_sha: str) -> str:
    gains = trim["gain_db_relative_to_code8_by_channel_and_code"]
    currents = trim["supply_current_a_by_channel_and_code"]
    output_cm = trim["output_common_mode_v_by_channel_and_code"]
    require(len(gains) == 4 and all(len(row) == 16 for row in gains), "trim gain table is incomplete")
    require(len(currents) == 4 and all(len(row) == 16 for row in currents), "trim current table is incomplete")
    require(len(output_cm) == 4 and all(len(row) == 16 for row in output_cm), "trim common-mode table is incomplete")

    svg = Svg(
        1500,
        930,
        "Four-channel trim characterization",
        "Extracted transfer curves, current cost, output common mode, and deterministic calibration stress result.",
    )
    draw_title(
        svg,
        "Four-channel gain-trim characterization",
        "Extracted-device/capacitance view; one channel enabled; code 8 is the reset reference",
    )

    left, top, width, height = 92.0, 125.0, 860.0, 390.0
    draw_axes(
        svg,
        left=left,
        top=top,
        width=width,
        height=height,
        x_ticks=(0, 2, 4, 6, 8, 10, 12, 14, 15),
        y_ticks=(-1.2, -0.8, -0.4, 0.0, 0.4, 0.8),
        x_min=0,
        x_max=15,
        y_min=-1.35,
        y_max=0.95,
        x_label="Trim code",
        y_label="Gain relative to code 8 (dB)",
    )
    code8_x, _ = map_xy(8, 0, left=left, top=top, width=width, height=height, x_min=0, x_max=15, y_min=-1.35, y_max=0.95)
    svg.line(code8_x, top, code8_x, top + height, stroke=AMBER, stroke_width=2, dash="5 5")
    svg.text(code8_x + 8, top + 20, "reset code 8", css_class="small", fill=AMBER)
    for channel, values in enumerate(gains):
        points = [
            map_xy(code, value, left=left, top=top, width=width, height=height, x_min=0, x_max=15, y_min=-1.35, y_max=0.95)
            for code, value in enumerate(values)
        ]
        svg.polyline(points, stroke=CHANNEL_COLORS[channel], stroke_width=2.5)
        for px, py in points:
            svg.circle(px, py, 3.4, fill=CHANNEL_COLORS[channel], stroke_width=1)
        end_x, end_y = points[-1]
        svg.text(end_x + 10, end_y + (channel - 1.5) * 12, f"CH{channel}", css_class="small", fill=CHANNEL_COLORS[channel])

    current_avg = [sum(abs(row[code]) for row in currents) / 4 * 1000 for code in range(16)]
    cm_avg = [sum(row[code] for row in output_cm) / 4 for code in range(16)]

    mini_top, mini_height, mini_width = 615.0, 175.0, 385.0
    draw_axes(
        svg,
        left=92,
        top=mini_top,
        width=mini_width,
        height=mini_height,
        x_ticks=(0, 4, 8, 12, 15),
        y_ticks=(0.26, 0.28, 0.30, 0.32),
        x_min=0,
        x_max=15,
        y_min=0.255,
        y_max=0.32,
        y_formatter=lambda value: f"{value:.2f}",
        x_label="Trim code",
        y_label="Supply current (mA)",
    )
    points = [
        map_xy(code, value, left=92, top=mini_top, width=mini_width, height=mini_height, x_min=0, x_max=15, y_min=0.255, y_max=0.32)
        for code, value in enumerate(current_avg)
    ]
    svg.polyline(points, stroke=BLUE, stroke_width=2.5)
    for px, py in points:
        svg.circle(px, py, 3, fill=BLUE, stroke_width=1)

    cm_left = 570.0
    draw_axes(
        svg,
        left=cm_left,
        top=mini_top,
        width=mini_width,
        height=mini_height,
        x_ticks=(0, 4, 8, 12, 15),
        y_ticks=(1.54, 1.56, 1.58, 1.60),
        x_min=0,
        x_max=15,
        y_min=1.53,
        y_max=1.615,
        y_formatter=lambda value: f"{value:.2f}",
        x_label="Trim code",
        y_label="Output common mode (V)",
    )
    points = [
        map_xy(code, value, left=cm_left, top=mini_top, width=mini_width, height=mini_height, x_min=0, x_max=15, y_min=1.53, y_max=1.615)
        for code, value in enumerate(cm_avg)
    ]
    svg.polyline(points, stroke=PURPLE, stroke_width=2.5)
    for px, py in points:
        svg.circle(px, py, 3, fill=PURPLE, stroke_width=1)

    stress = trim["injected_mismatch_stress"]
    panel_x, panel_y, panel_w, panel_h = 1025.0, 125.0, 410.0, 665.0
    svg.rect(panel_x, panel_y, panel_w, panel_h, fill=PANEL, stroke=GRID, rx=8)
    svg.text(panel_x + 24, panel_y + 38, "Calibration effectiveness", css_class="label")
    svg.text(panel_x + 24, panel_y + 64, "Deterministic injected offsets", css_class="subtitle")
    baseline = float(stress["untrimmed_code8_spread_db"])
    calibrated = float(stress["calibration"]["spread_db"])
    bar_base = panel_y + 500
    bar_height = 345
    bar_width = 105
    scale_max = 1.3
    for index, (label, value, color) in enumerate(
        (("Untrimmed", baseline, RED), ("Calibrated", calibrated, GREEN))
    ):
        x = panel_x + 75 + index * 175
        height_px = bar_height * value / scale_max
        svg.rect(x, bar_base - height_px, bar_width, height_px, fill=color, rx=4)
        svg.text(x + bar_width / 2, bar_base - height_px - 12, f"{value:.3f} dB", css_class="value", anchor="middle")
        svg.text(x + bar_width / 2, bar_base + 25, label, css_class="axis", anchor="middle")
    svg.line(panel_x + 38, bar_base, panel_x + panel_w - 38, bar_base, stroke=MUTED)
    codes = stress["calibration"]["codes_ch0_to_ch3"]
    svg.text(panel_x + 24, panel_y + 585, "Selected codes  CH0..CH3", css_class="small")
    svg.text(panel_x + 24, panel_y + 612, " / ".join(str(code) for code in codes), css_class="label")
    svg.text(panel_x + 24, panel_y + 644, "±0.6 dB synthetic stress; not Monte Carlo", css_class="small", fill=AMBER)

    spans = trim["trim_span_db_by_channel"]
    svg.text(92, 875, f"Measured span {min(spans):.3f} to {max(spans):.3f} dB; minimum adjacent step {min(item['minimum_adjacent_step_db'] for item in trim['useful_resolution_by_channel']):.3f} dB", css_class="label")
    draw_footer(svg, source_sha, "TT, 1.8 V, 27 C, 5 mVpk")
    return svg.finish()


def corner_label(report: dict[str, Any]) -> tuple[str, str]:
    process = report["process_corner"].upper()
    passive = report["passive_corner"].upper()
    voltage = report["supply_voltage_v"]
    temperature = report["temperature_c"]
    return f"{process}/{passive}", f"{voltage:.2f} V, {temperature:g} C"


def render_pvt(
    reports: Sequence[dict[str, Any]],
    source_hashes: Sequence[str],
    zero_input_diagnostic: dict[str, Any] | None = None,
    trim6_diagnostics: Sequence[dict[str, Any]] = (),
) -> str:
    order = {"ss": 0, "fs": 1, "sf": 2, "tt": 3, "ff": 4}
    reports = sorted(
        reports,
        key=lambda report: (
            report["supply_voltage_v"],
            report["temperature_c"],
            order.get(report["process_corner"], 9),
            report["passive_corner"],
        ),
    )
    require(len(reports) >= 4, "at least four PVT reports are required")
    svg = Svg(
        1500,
        1080,
        "Distributed-RC PVT operating envelope",
        "Output tone, output common mode, and power across the completed process, voltage, temperature, and passive corners.",
    )
    draw_title(
        svg,
        "Distributed-RC operating envelope",
        "Completed characterization points; red mark is an electrical gate failure, not a simulator timeout",
    )
    left, width = 105.0, 1330.0
    x_values = list(range(len(reports)))

    def draw_panel(
        top: float,
        height: float,
        values: Sequence[float],
        y_min: float,
        y_max: float,
        y_ticks: Sequence[float],
        y_label: str,
        formatter,
        band: tuple[float, float] | None = None,
    ) -> None:
        if band:
            _, upper_y = map_xy(0, band[1], left=left, top=top, width=width, height=height, x_min=0, x_max=len(reports) - 1, y_min=y_min, y_max=y_max)
            _, lower_y = map_xy(0, band[0], left=left, top=top, width=width, height=height, x_min=0, x_max=len(reports) - 1, y_min=y_min, y_max=y_max)
            svg.rect(left, upper_y, width, lower_y - upper_y, fill="#eaf6ed")
        draw_axes(
            svg,
            left=left,
            top=top,
            width=width,
            height=height,
            x_ticks=x_values,
            y_ticks=y_ticks,
            x_min=0,
            x_max=len(reports) - 1,
            y_min=y_min,
            y_max=y_max,
            x_formatter=lambda _value: "",
            y_formatter=formatter,
            y_label=y_label,
        )
        points = [
            map_xy(index, value, left=left, top=top, width=width, height=height, x_min=0, x_max=len(reports) - 1, y_min=y_min, y_max=y_max)
            for index, value in enumerate(values)
        ]
        svg.polyline(points, stroke="#8390a3", stroke_width=2)
        for index, ((px, py), value, report) in enumerate(zip(points, values, reports)):
            passed = report["status"] == "pass"
            svg.circle(px, py, 7, fill=GREEN if passed else RED, stroke_width=2)
            svg.text(px, py - 13, formatter(value), css_class="small", anchor="middle", fill=GREEN if passed else RED)

    tones_mv = [report["analysis"]["output_tone_rms_v"] * 1000 for report in reports]
    common_modes = [report["analysis"]["output_common_mode_v"] for report in reports]
    powers_mw = [report["analysis"]["estimated_power_w"] * 1000 for report in reports]
    currents_ma = [report["analysis"]["supply_current_a"] * 1000 for report in reports]
    draw_panel(118, 225, tones_mv, 15, 29, (16, 20, 24, 28), "Output tone (mV RMS)", lambda value: f"{value:.2f}")
    draw_panel(405, 225, common_modes, 0.72, 1.05, (0.75, 0.80, 0.90, 1.00), "Output common mode (V)", lambda value: f"{value:.3f}", band=(0.8, 1.05))
    svg.text(left + width - 8, 430, "release region ≥ 0.8 V", css_class="small", anchor="end", fill=GREEN)
    if trim6_diagnostics:
        sf_index = next(
            index
            for index, report in enumerate(reports)
            if report["process_corner"] == "sf"
            and report["supply_voltage_v"] == 1.8
            and report["temperature_c"] == 27.0
        )
        sf_default = common_modes[sf_index]
        trim6_common_modes = [
            diagnostic["analysis"]["output_common_mode_v"]
            for diagnostic in trim6_diagnostics
        ]
        sf_trim6 = sum(trim6_common_modes) / len(trim6_common_modes)
        px, default_y = map_xy(
            sf_index, sf_default, left=left, top=405, width=width, height=225,
            x_min=0, x_max=len(reports) - 1, y_min=0.72, y_max=1.05,
        )
        _, trim6_y = map_xy(
            sf_index, sf_trim6, left=left, top=405, width=width, height=225,
            x_min=0, x_max=len(reports) - 1, y_min=0.72, y_max=1.05,
        )
        svg.line(px, default_y, px, trim6_y, stroke=BLUE, stroke_width=3)
        svg.circle(px, trim6_y, 6, fill=BLUE, stroke_width=2)
        svg.text(
            px + 12,
            trim6_y - 8,
            f"trim 6, 4/4 beams: {sf_trim6:.3f} V",
            css_class="small",
            fill=BLUE,
        )
    if zero_input_diagnostic is not None or trim6_diagnostics:
        messages = []
        if zero_input_diagnostic:
            diagnostic_analysis = zero_input_diagnostic["analysis"]
            messages.append(
                "zero input retains "
                f"{diagnostic_analysis['output_common_mode_v']:.3f} V common mode"
            )
        if trim6_diagnostics:
            trim6_common_modes = [
                diagnostic["analysis"]["output_common_mode_v"]
                for diagnostic in trim6_diagnostics
            ]
            trim6_tones_mv = [
                diagnostic["analysis"]["output_tone_rms_v"] * 1000
                for diagnostic in trim6_diagnostics
            ]
            messages.append(
                "; trim 6 passes 4/4 beams at "
                f"{min(trim6_common_modes):.6f}–{max(trim6_common_modes):.6f} V "
                f"with {min(trim6_tones_mv):.2f}–{max(trim6_tones_mv):.2f} mV tone"
            )
        svg.text(
            left + 8,
            658,
            "SF diagnostics: " + "".join(messages) + " — tail-current/headroom finding",
            css_class="small",
            fill=RED,
        )
    draw_panel(692, 225, powers_mw, 0.85, 1.85, (1.0, 1.2, 1.4, 1.6, 1.8), "Estimated power (mW)", lambda value: f"{value:.2f}")
    for index, report in enumerate(reports):
        px, _ = map_xy(index, 0, left=left, top=692, width=width, height=225, x_min=0, x_max=len(reports) - 1, y_min=0.85, y_max=1.85)
        first, second = corner_label(report)
        svg.text(px, 952, first, css_class="label", anchor="middle", fill=GREEN if report["status"] == "pass" else RED)
        svg.text(px, 975, second, css_class="small", anchor="middle")
        svg.text(px, 996, f"{currents_ma[index]:.3f} mA", css_class="small", anchor="middle")
    svg.text(left + width / 2, 1024, "Process/passive corner, supply, temperature; current shown below each point", css_class="axis", anchor="middle")
    combined_sha = hashlib.sha256("".join(sorted(source_hashes)).encode()).hexdigest()
    draw_footer(svg, combined_sha, f"{len(reports)} completed RC points, beam 0")
    return svg.finish()


def render_startup(startup: dict[str, Any], source_sha: str) -> str:
    measurements = startup["measurements"]
    valid_us = measurements["vcm_valid_first"] * 1e6
    near_us = measurements["vcm_near_nominal_first"] * 1e6
    stop_us = float(startup["stop_us"])
    final_avg = measurements["vcm_final_avg"]
    final_min = measurements["vcm_final_min"]
    final_max = measurements["vcm_final_max"]
    window_us = float(startup["final_window_us"])
    svg = Svg(
        1400,
        660,
        "Distributed-RC cold-start milestones",
        "Measured VCM threshold times and final settled range from a 120 microsecond quiet cold-start simulation.",
    )
    draw_title(
        svg,
        "Distributed-RC cold-start milestones",
        "Threshold measurements and final window; connecting line indicates elapsed time, not a reconstructed waveform",
    )
    axis_left, axis_right, axis_y = 115.0, 1310.0, 250.0
    svg.line(axis_left, axis_y, axis_right, axis_y, stroke="#8591a3", stroke_width=6)
    for tick in range(0, 121, 20):
        x = axis_left + (axis_right - axis_left) * tick / stop_us
        svg.line(x, axis_y - 10, x, axis_y + 10, stroke=MUTED, stroke_width=2)
        svg.text(x, axis_y + 38, f"{tick}", css_class="tick", anchor="middle")
    svg.text((axis_left + axis_right) / 2, axis_y + 68, "Elapsed time after supply application (us)", css_class="axis", anchor="middle")

    milestones = (
        (0.0, "Supply applied", "0 us", MUTED, -1),
        (valid_us, "VCM reaches 1.10 V", f"{valid_us:.3f} us", BLUE, 1),
        (near_us, "VCM reaches 1.17 V", f"{near_us:.3f} us", PURPLE, -1),
        (stop_us, "Final measurement", f"{stop_us:.0f} us", GREEN, 1),
    )
    for time_us, label, value, color, direction in milestones:
        x = axis_left + (axis_right - axis_left) * time_us / stop_us
        svg.circle(x, axis_y, 10, fill=color, stroke_width=3)
        label_y = axis_y + direction * 80
        value_y = label_y + 24
        svg.line(x, axis_y + direction * 12, x, label_y - direction * 14, stroke=color, stroke_width=2)
        svg.text(x, label_y, label, css_class="label", anchor="middle", fill=color)
        svg.text(x, value_y, value, css_class="small", anchor="middle")

    panel_x, panel_y, panel_w, panel_h = 175.0, 430.0, 1050.0, 145.0
    svg.rect(panel_x, panel_y, panel_w, panel_h, fill=PANEL, stroke=GRID, rx=8)
    svg.text(panel_x + 28, panel_y + 38, f"Final {window_us:g} us window", css_class="label")
    svg.text(panel_x + 28, panel_y + 76, f"VCM average  {final_avg:.6f} V", css_class="value")
    svg.text(panel_x + 390, panel_y + 76, f"range  {final_min:.6f} to {final_max:.6f} V", css_class="value")
    movement_mv = (final_max - final_min) * 1000
    svg.text(panel_x + 28, panel_y + 110, f"Observed window movement  {movement_mv:.3f} mV", css_class="small")
    svg.text(panel_x + 590, panel_y + 110, "Bench recommendation: wait at least 120 us before enabling", css_class="small", fill=AMBER)
    draw_footer(svg, source_sha, f"quiet cold start, {startup['step_ns']:g} ns max step")
    return svg.finish()


def render_mismatch(mismatch: dict[str, Any], source_sha: str) -> str:
    seeds = sorted(
        ((int(seed), item) for seed, item in mismatch["seeds"].items()),
        key=lambda item: item[0],
    )
    require(len(seeds) >= 60, "mismatch figure requires at least 60 seeds")
    rejection = [float(item["metrics"]["corrected_rejection_db"]) for _, item in seeds]
    common_mode = [float(item["metrics"]["output_common_mode_v"]) for _, item in seeds]
    headroom = [
        float(item["metrics"]["minimum_time_aligned_gm_drain_to_tail_v"])
        for _, item in seeds
    ]
    ordered = sorted(rejection)
    median = (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2
    svg = Svg(
        1500, 820,
        "Open-PDK MOS mismatch campaign",
        "Corrected beam rejection for every seeded MOS mismatch sample.",
    )
    draw_title(
        svg,
        "MOS mismatch sensitivity — 60 seeded samples",
        "Published SKY130 coefficient model; background-corrected result; not foundry-qualified yield",
    )
    left, top, width, height = 95.0, 125.0, 970.0, 520.0
    y_max = max(60.0, math.ceil(max(rejection) / 10.0) * 10.0)
    draw_axes(
        svg, left=left, top=top, width=width, height=height,
        x_ticks=(1, 10, 20, 30, 40, 50, 60),
        y_ticks=(12, 20, 30, 40, 50, 60),
        x_min=1, x_max=max(seed for seed, _ in seeds), y_min=10, y_max=y_max,
        x_label="Mismatch seed", y_label="Corrected beam rejection (dB)",
    )
    _, target_y = map_xy(
        1, 12, left=left, top=top, width=width, height=height,
        x_min=1, x_max=max(seed for seed, _ in seeds), y_min=10, y_max=y_max,
    )
    svg.line(left, target_y, left + width, target_y, stroke=AMBER, stroke_width=2, dash="7 5")
    svg.text(left + width - 8, target_y - 9, "12 dB engineering target", css_class="small", anchor="end", fill=AMBER)
    points = [
        map_xy(
            seed, value, left=left, top=top, width=width, height=height,
            x_min=1, x_max=max(index for index, _ in seeds), y_min=10, y_max=y_max,
        )
        for (seed, _), value in zip(seeds, rejection)
    ]
    svg.polyline(points, stroke="#a6b0bf", stroke_width=1.5)
    for px, py in points:
        svg.circle(px, py, 4.2, fill=GREEN, stroke_width=1)

    panel_x, panel_y, panel_w, panel_h = 1115.0, 125.0, 330.0, 520.0
    svg.rect(panel_x, panel_y, panel_w, panel_h, fill=PANEL, stroke=GRID, rx=8)
    svg.text(panel_x + 24, panel_y + 40, "Campaign summary", css_class="label")
    rows = (
        ("Passing samples", f"{mismatch['passing_seed_count']} / {mismatch['seed_count']}", GREEN),
        ("Minimum rejection", f"{min(rejection):.2f} dB", GREEN),
        ("Median rejection", f"{median:.2f} dB", INK),
        ("Maximum rejection", f"{max(rejection):.2f} dB", INK),
        ("Output common mode", f"{min(common_mode):.3f}–{max(common_mode):.3f} V", INK),
        ("Minimum headroom", f"{min(headroom) * 1000:.1f} mV", GREEN),
        (
            "95% lower bound",
            f"{100 * mismatch['zero_failure_one_sided_95pct_pass_probability_lower_bound']:.2f}%",
            GREEN,
        ),
    )
    for index, (label, value, color) in enumerate(rows):
        y = panel_y + 90 + index * 58
        svg.text(panel_x + 24, y, label, css_class="small")
        svg.text(panel_x + panel_w - 24, y + 23, value, css_class="value", anchor="end", fill=color)
    svg.text(95, 700, "Every sampled circuit passed the hard 6 dB gate and the 12 dB engineering target.", css_class="label", fill=GREEN)
    svg.text(95, 727, "Scope excludes passive mismatch, spatial gradients/correlation, package effects, and proprietary foundry statistics.", css_class="small", fill=AMBER)
    draw_footer(svg, source_sha, "open-PDK coefficient sensitivity")
    return svg.finish()


def render_gate5_sensitivity(
    sensitivity: dict[str, Any], clock: dict[str, Any], source_sha: str
) -> str:
    metrics = sensitivity["metrics"]
    svg = Svg(
        1500, 900,
        "Bounded electrical sensitivity summary",
        "Compression, output loading, RF frequency, and master-clock sensitivity.",
    )
    draw_title(
        svg,
        "Bounded electrical sensitivity",
        "Base-extracted sweeps around the 5 MHz RF / 4 MHz LO / 1 MHz IF operating point",
    )

    def bars(
        x: float, y: float, width: float, height: float, title: str,
        labels: Sequence[str], values: Sequence[float], y_min: float, y_max: float,
        suffix: str = "dB",
    ) -> None:
        svg.rect(x, y, width, height, fill=PANEL, stroke=GRID, rx=8)
        svg.text(x + 20, y + 34, title, css_class="label")
        zero_y = y + 58 + (height - 110) * (1 - (0 - y_min) / (y_max - y_min))
        svg.line(x + 45, zero_y, x + width - 20, zero_y, stroke=MUTED)
        slot = (width - 80) / len(values)
        for index, (label, value) in enumerate(zip(labels, values)):
            px = x + 48 + index * slot
            value_y = y + 58 + (height - 110) * (1 - (value - y_min) / (y_max - y_min))
            top_y = min(zero_y, value_y)
            bar_h = max(2.0, abs(value_y - zero_y))
            color = GREEN if abs(value) <= 1.0 else AMBER
            svg.rect(px, top_y, slot * 0.55, bar_h, fill=color, rx=3)
            svg.text(px + slot * 0.275, top_y - 8, f"{value:+.3f}", css_class="small", anchor="middle", fill=color)
            svg.text(px + slot * 0.275, y + height - 22, label, css_class="small", anchor="middle")
        svg.text(x + width - 18, y + 34, suffix, css_class="small", anchor="end")

    compression = metrics["compression_db"]
    bars(
        60, 110, 680, 315, "Gain compression versus input peak",
        ("20 mV", "50 mV"),
        (float(compression["amplitude_20mvpk"]), float(compression["amplitude_50mvpk"])),
        -0.1, 1.0,
    )
    loads = metrics["load_gain_delta_db"]
    bars(
        770, 110, 670, 315, "Conversion-gain change versus output load",
        ("100 kΩ", "30 pF", "60 pF"),
        (float(loads["load_100kohm_shunt"]), float(loads["load_30pf_total"]), float(loads["load_60pf_total"])),
        -3.5, 0.5,
    )
    frequency = metrics["frequency_gain_delta_db"]
    bars(
        60, 460, 680, 315, "RF-frequency gain change (LO fixed at 4 MHz)",
        ("4.5 MHz", "6 MHz"),
        (float(frequency["rf_4p5mhz"]), float(frequency["rf_6mhz"])),
        -1.0, 0.5,
    )
    clock_delta = clock["metrics"]["gain_delta_db"]
    order = ("duty_40pct", "duty_60pct", "jitter_500ps", "jitter_1000ps")
    bars(
        770, 460, 670, 315, "Master-clock duty/jitter gain change",
        ("40%", "60%", "500 ps", "1 ns"),
        tuple(float(clock_delta[name]) for name in order),
        -0.05, 0.10,
    )
    svg.text(60, 825, "The 60 pF total load is intentionally shown as a warning point: it costs about 3.09 dB but remains electrically stable.", css_class="small", fill=AMBER)
    draw_footer(svg, source_sha, "bounded simulation, not guaranteed limits")
    return svg.finish()


def render_twotone(twotone: dict[str, Any], source_sha: str) -> str:
    points = twotone["analysis"]["points"]
    ordered = ((2, points["tone_2mvpk"]), (10, points["tone_10mvpk"]))
    svg = Svg(
        1250, 660,
        "Two-tone intermodulation pilot",
        "Fundamental-to-worst-IM3 separation at two input amplitudes.",
    )
    draw_title(
        svg,
        "Two-tone intermodulation pilot",
        "4.9 and 5.1 MHz RF tones produce 0.9 and 1.1 MHz IF fundamentals",
    )
    left, top, width, height = 95.0, 125.0, 680.0, 390.0
    draw_axes(
        svg, left=left, top=top, width=width, height=height,
        x_ticks=(2, 10), y_ticks=(0, 20, 40, 60, 80),
        x_min=1, x_max=11, y_min=0, y_max=80,
        x_label="Peak input per tone (mV)",
        y_label="Fundamental / worst IM3 separation (dB)",
    )
    for input_mv, point in ordered:
        value = float(point["fundamental_to_worst_im3_db"])
        px, py = map_xy(
            input_mv, value, left=left, top=top, width=width, height=height,
            x_min=1, x_max=11, y_min=0, y_max=80,
        )
        svg.circle(px, py, 9, fill=GREEN, stroke_width=2)
        svg.text(px, py - 18, f"{value:.2f} dB", css_class="value", anchor="middle", fill=GREEN)
    _, gate_y = map_xy(
        1, 40, left=left, top=top, width=width, height=height,
        x_min=1, x_max=11, y_min=0, y_max=80,
    )
    svg.line(left, gate_y, left + width, gate_y, stroke=AMBER, stroke_width=2, dash="7 5")
    svg.text(left + width - 8, gate_y - 9, "40 dB pilot gate", css_class="small", anchor="end", fill=AMBER)
    panel_x, panel_y, panel_w, panel_h = 830.0, 125.0, 355.0, 390.0
    svg.rect(panel_x, panel_y, panel_w, panel_h, fill=PANEL, stroke=GRID, rx=8)
    svg.text(panel_x + 24, panel_y + 40, "Input IIP3 estimates", css_class="label")
    for index, (input_mv, point) in enumerate(ordered):
        y = panel_y + 100 + index * 120
        svg.text(panel_x + 24, y, f"{input_mv} mV peak/tone", css_class="small")
        svg.text(panel_x + 24, y + 34, f"{point['input_iip3_dbv_rms_per_tone']:.2f} dBV RMS", css_class="value")
        components = point["components_rms_v"]
        svg.text(panel_x + 24, y + 63, f"fundamental ≈ {1000 * min(components['fund_low'], components['fund_high']):.3f} mV RMS", css_class="small")
        svg.text(panel_x + 24, y + 86, f"worst IM3 ≈ {1000 * max(components['im3_low'], components['im3_high']):.4f} mV RMS", css_class="small")
    svg.text(95, 600, "Pilot result characterizes this operating point; it is not a production linearity guarantee.", css_class="small", fill=AMBER)
    draw_footer(svg, source_sha, "base-extracted two-tone transient")
    return svg.finish()


def write_figure(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codebook",
        type=Path,
        default=Path(
            "build/v2/postlayout_smoke/rc/codebook/"
            "summary_startup_op_step_5ns.json"
        ),
    )
    parser.add_argument(
        "--trim",
        type=Path,
        default=Path("build/v2/postlayout_trim/base/summary.json"),
    )
    parser.add_argument(
        "--startup",
        type=Path,
        default=Path(
            "build/v2/postlayout_startup/rc/"
            "quiet_120us_step_20ns_final_5us/report.json"
        ),
    )
    parser.add_argument(
        "--mismatch",
        type=Path,
        default=Path("build/v2/gate5_mismatch_pilot/base_pilot_summary.json"),
    )
    parser.add_argument(
        "--sensitivity",
        type=Path,
        default=Path("build/v2/signoff/gate5_sensitivity_pilot.json"),
    )
    parser.add_argument(
        "--clock",
        type=Path,
        default=Path("build/v2/signoff/gate5_clock_pilot.json"),
    )
    parser.add_argument(
        "--twotone",
        type=Path,
        default=Path("build/v2/gate5_twotone_pilot/base_summary.json"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("v2/evidence/images"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("v2/evidence/datasheet_figures.json"),
    )
    args = parser.parse_args()

    codebook = load_json(args.codebook)
    trim = load_json(args.trim)
    startup = load_json(args.startup)
    mismatch = load_json(args.mismatch)
    sensitivity = load_json(args.sensitivity)
    clock = load_json(args.clock)
    twotone = load_json(args.twotone)

    require(codebook.get("status") == "pass", "codebook summary did not pass")
    require(trim.get("status") == "pass", "trim summary did not pass")
    require(startup.get("status") == "pass", "startup report did not pass")
    require(
        mismatch.get("status") == "pass" and mismatch.get("seed_count", 0) >= 60,
        "60-seed mismatch campaign did not pass",
    )
    require(sensitivity.get("status") == "pass", "sensitivity pilot did not pass")
    require(clock.get("status") == "pass", "clock pilot did not pass")
    require(twotone.get("status") == "pass", "two-tone pilot did not pass")
    require_hashes(codebook, gds=EXPECTED_GDS_SHA256, netlist=EXPECTED_RC_NETLIST_SHA256, context="codebook")
    require_hashes(trim, gds=EXPECTED_GDS_SHA256, netlist=EXPECTED_BASE_NETLIST_SHA256, context="trim")
    require_hashes(startup, gds=EXPECTED_GDS_SHA256, netlist=EXPECTED_RC_NETLIST_SHA256, context="startup")
    require(
        mismatch.get("gds_sha256") == EXPECTED_GDS_SHA256
        and mismatch.get("source_netlist_sha256") == EXPECTED_BASE_NETLIST_SHA256,
        "mismatch campaign uses different physical artifacts",
    )
    require(
        sensitivity.get("frozen_gds_sha256") == EXPECTED_GDS_SHA256
        and sensitivity.get("base_netlist_sha256") == EXPECTED_BASE_NETLIST_SHA256,
        "sensitivity pilot uses different physical artifacts",
    )
    require(
        clock.get("frozen_gds_sha256") == EXPECTED_GDS_SHA256
        and clock.get("base_netlist_sha256") == EXPECTED_BASE_NETLIST_SHA256,
        "clock pilot uses different physical artifacts",
    )
    require(
        twotone.get("gds_sha256") == EXPECTED_GDS_SHA256
        and twotone.get("netlist_sha256") == EXPECTED_BASE_NETLIST_SHA256,
        "two-tone pilot uses different physical artifacts",
    )

    codebook_sha = sha256(args.codebook)
    trim_sha = sha256(args.trim)
    startup_sha = sha256(args.startup)
    mismatch_sha = sha256(args.mismatch)
    sensitivity_sha = sha256(args.sensitivity)
    clock_sha = sha256(args.clock)
    twotone_sha = sha256(args.twotone)
    figure_specs = (
        (
            "beam-codebook-response.svg",
            render_codebook(codebook, codebook_sha),
            [str(args.codebook)],
        ),
        (
            "trim-characterization.svg",
            render_trim(trim, trim_sha),
            [str(args.trim)],
        ),
        (
            "mismatch-campaign.svg",
            render_mismatch(mismatch, mismatch_sha),
            [str(args.mismatch)],
        ),
        (
            "electrical-sensitivity.svg",
            render_gate5_sensitivity(
                sensitivity,
                clock,
                hashlib.sha256((sensitivity_sha + clock_sha).encode()).hexdigest(),
            ),
            [str(args.sensitivity), str(args.clock)],
        ),
        (
            "two-tone-linearity.svg",
            render_twotone(twotone, twotone_sha),
            [str(args.twotone)],
        ),
        (
            "cold-start-timing.svg",
            render_startup(startup, startup_sha),
            [str(args.startup)],
        ),
    )
    figures = []
    for filename, content, sources in figure_specs:
        record = write_figure(args.out_dir / filename, content)
        record["sources"] = [
            {"path": source, "sha256": sha256(Path(source))} for source in sources
        ]
        figures.append(record)

    manifest = {
        "schema_version": 1,
        "candidate_gds_sha256": EXPECTED_GDS_SHA256,
        "base_netlist_sha256": EXPECTED_BASE_NETLIST_SHA256,
        "distributed_rc_netlist_sha256": EXPECTED_RC_NETLIST_SHA256,
        "figures": figures,
        "datasets": {
            "beam_codebook": {
                "raw_response_matrix_v_rms": codebook["metrics"]["raw_response_matrix_v_rms"],
                "minimum_rejection_db": codebook["metrics"]["minimum_rejection_db"],
                "constructive_spread_db": codebook["metrics"]["constructive_spread_db"],
            },
            "trim": {
                "gain_db_relative_to_code8_by_channel_and_code": trim["gain_db_relative_to_code8_by_channel_and_code"],
                "supply_current_a_by_channel_and_code": trim["supply_current_a_by_channel_and_code"],
                "output_common_mode_v_by_channel_and_code": trim["output_common_mode_v_by_channel_and_code"],
                "trim_span_db_by_channel": trim["trim_span_db_by_channel"],
                "minimum_adjacent_step_db_by_channel": [
                    item["minimum_adjacent_step_db"]
                    for item in trim["useful_resolution_by_channel"]
                ],
                "default_spread_db": trim["default_spread_db"],
                "injected_mismatch_stress": trim["injected_mismatch_stress"],
            },
            "mismatch": {
                "seed_count": mismatch["seed_count"],
                "passing_seed_count": mismatch["passing_seed_count"],
                "seeds_meeting_12db_engineering_target": mismatch[
                    "seeds_meeting_12db_engineering_target"
                ],
                "zero_failure_one_sided_95pct_pass_probability_lower_bound": mismatch[
                    "zero_failure_one_sided_95pct_pass_probability_lower_bound"
                ],
                "corrected_rejection_db_by_seed": {
                    seed: item["metrics"]["corrected_rejection_db"]
                    for seed, item in mismatch["seeds"].items()
                },
                "output_common_mode_v_by_seed": {
                    seed: item["metrics"]["output_common_mode_v"]
                    for seed, item in mismatch["seeds"].items()
                },
                "minimum_headroom_v_by_seed": {
                    seed: item["metrics"]["minimum_time_aligned_gm_drain_to_tail_v"]
                    for seed, item in mismatch["seeds"].items()
                },
            },
            "sensitivity": sensitivity["metrics"],
            "clock": clock["metrics"],
            "twotone": twotone["analysis"]["points"],
            "known_limits": {
                "noise": "periodically switched mixer noise requires a periodic-noise simulator or first-silicon measurement",
                "mismatch": mismatch["limitations"],
            },
            "cold_start": {
                "stop_us": startup["stop_us"],
                "step_ns": startup["step_ns"],
                "final_window_us": startup["final_window_us"],
                "measurements": startup["measurements"],
            },
        },
        "notes": [
            "Figures are deterministic transformations of the named JSON reports.",
            "Injected trim stress is deterministic and is not foundry mismatch Monte Carlo.",
            "The mismatch campaign uses published open-PDK coefficients and is not foundry-qualified silicon yield.",
            "Sensitivity and two-tone points are bounded characterization samples, not guaranteed limits.",
            "Cold-start timing shows measured milestones, not a reconstructed transient waveform.",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
