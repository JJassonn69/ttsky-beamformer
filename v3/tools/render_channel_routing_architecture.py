#!/usr/bin/env python3
"""Render the V3 routing-architecture comparison and selected tile skeleton."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "v3/layout/channel_routing_architecture.json"
DEFAULT_COMPARE = ROOT / "v3/evidence/channel_routing_architecture_review.svg"
DEFAULT_TILE = ROOT / "v3/evidence/channel_routing_architecture_tile_review.svg"

COLORS = {
    "device": "#65758b",
    "output": "#38bdf8",
    "analog": "#f59e0b",
    "phase": "#c084fc",
    "phase_m3": "#e879f9",
    "guard": "#4ade80",
    "support": "#f97316",
    "selector": "#ef4444",
    "ground": "#22c55e",
}


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none", opacity: float = 1.0, rx: float = 0.0) -> str:
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}" stroke="{stroke}" opacity="{opacity:.3f}" rx="{rx:.2f}"/>'


def text(x: float, y: float, value: str, size: float = 13, colour: str = "#e5edf7", weight: str = "normal", anchor: str = "start") -> str:
    return f'<text x="{x:.2f}" y="{y:.2f}" fill="{colour}" font-family="Inter,Arial,sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(value)}</text>'


def channel_panel(candidate: dict[str, Any], ox: float, oy: float, scale: float, title: str) -> list[str]:
    width = candidate["channel_bbox"][2]
    height = candidate["channel_bbox"][3]

    def sx(value: float) -> float:
        return ox + value * scale

    def sy(value: float) -> float:
        return oy + (height - value) * scale

    pieces = [
        text(ox, oy - 22, title, 18, "#ffffff", "bold"),
        text(ox, oy - 4, f"score {candidate['score_total']}/100 · {candidate['geometry_status']}", 12, "#aebdd0"),
        rect(ox, oy, width * scale, height * scale, "#111827", "#94a3b8", 1.0, 3),
    ]
    origins = candidate["column_origins_um"]
    unit = [-0.85, 0.0, 3.71, 12.365]
    for row_y in candidate["row_origins_top_to_bottom_um"]:
        for origin_x in origins:
            x0 = origin_x + unit[0]
            y1 = row_y + unit[3]
            pieces.append(rect(sx(x0), sy(y1), (unit[2] - unit[0]) * scale, unit[3] * scale, COLORS["device"], "#9aabba", 0.55, 2))

    for name, corridor in candidate.get("service_corridors", {}).items():
        bbox = corridor["bbox"]
        colour = COLORS["output"] if "output" in name else COLORS["analog"] if "analog" in name else COLORS["support"]
        pieces.append(rect(sx(bbox[0]), sy(bbox[3]), (bbox[2]-bbox[0])*scale, (bbox[3]-bbox[1])*scale, colour, colour, 0.12, 2))
        for net, x_value in corridor.get("spines", {}).items():
            line_width = max(2.4, corridor.get("width_um", 0.4) * scale)
            pieces.append(f'<line x1="{sx(x_value):.2f}" y1="{sy(bbox[1]):.2f}" x2="{sx(x_value):.2f}" y2="{sy(bbox[3]):.2f}" stroke="{colour}" stroke-width="{line_width:.2f}"/>')

    phase = candidate["phase_distribution"]
    for x_value in phase.get("internal_g1_trunks_x_um", []):
        pieces.append(f'<line x1="{sx(x_value):.2f}" y1="{sy(20.7):.2f}" x2="{sx(x_value):.2f}" y2="{sy(112.0):.2f}" stroke="{COLORS["phase"]}" stroke-width="3"/>')
    for x_value in phase.get("side_bank_trunks_x_um", []):
        pieces.append(f'<line x1="{sx(x_value):.2f}" y1="{sy(20.7):.2f}" x2="{sx(x_value):.2f}" y2="{sy(112.0):.2f}" stroke="{COLORS["phase"]}" stroke-width="3"/>')
    if not phase.get("side_bank_trunks_x_um") and phase.get("side_bank_bbox"):
        bbox = phase["side_bank_bbox"]
        pieces.append(rect(sx(bbox[0]), sy(bbox[3]), (bbox[2]-bbox[0])*scale, (bbox[3]-bbox[1])*scale, COLORS["phase"], COLORS["phase"], 0.30, 2))

    for record in candidate["row_track_plan"]:
        tracks = record["tracks"]
        for key, y_value in tracks.items():
            if key.startswith("phase"):
                colour = COLORS["phase_m3"]
                x0, x1 = 0.7, width - 0.7
            elif key.startswith("output"):
                colour = COLORS["output"]
                x0, x1 = 1.0, width - 1.0
            elif key.startswith("next_row"):
                colour = COLORS["analog"]
                x0, x1 = 1.0, width - 1.0
            else:
                continue
            pieces.append(f'<line x1="{sx(x0):.2f}" y1="{sy(y_value):.2f}" x2="{sx(x1):.2f}" y2="{sy(y_value):.2f}" stroke="{colour}" stroke-width="1.4" opacity="0.82"/>')

    pieces.append(text(ox + 6, oy + height * scale - 8, "bottom: input / dummy / guard", 10, "#b9c6d5"))
    return pieces


def render_compare(data: dict[str, Any], output: Path) -> None:
    scale = 5.2
    panel_width = 19.32 * scale
    panel_height = 112.99 * scale
    left_x, right_x, top_y = 45.0, 215.0, 120.0
    canvas_w, canvas_h = 830, 790
    selected = data["decision"]["selected"]
    a = data["candidates"]["dual_service_corridors"]
    b = data["candidates"]["same_side_layer_overlay"]
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}">',
        rect(0, 0, canvas_w, canvas_h, "#0b1018"),
        text(40, 38, "V3 whole-channel routing architecture", 24, "#ffffff", "bold"),
        text(40, 62, "Every vertical spine and every inter-row track is reserved before exact routing.", 14, "#aebdd0"),
    ]
    pieces += channel_panel(a, left_x, top_y, scale, "A · dual corridors · selected")
    pieces += channel_panel(b, right_x, top_y, scale, "B · same-side overlay")
    legend_x = 390
    legend_y = 118
    pieces += [
        text(legend_x, legend_y, "Layer / ownership", 16, "#ffffff", "bold"),
        rect(legend_x, legend_y + 16, 18, 5, COLORS["output"]), text(legend_x + 28, legend_y + 23, "output: M2 spines + M3 row buses", 12),
        rect(legend_x, legend_y + 42, 18, 5, COLORS["analog"]), text(legend_x + 28, legend_y + 49, "signal / bias / ref: M2 spines", 12),
        rect(legend_x, legend_y + 68, 18, 5, COLORS["phase"]), text(legend_x + 28, legend_y + 75, "phase: M4 trunks", 12),
        rect(legend_x, legend_y + 94, 18, 5, COLORS["phase_m3"]), text(legend_x + 28, legend_y + 101, "phase: M3 row branches", 12),
        rect(legend_x, legend_y + 120, 18, 8, COLORS["device"], opacity=0.7), text(legend_x + 28, legend_y + 128, "exact vector-unit envelopes", 12),
        text(legend_x, legend_y + 170, "Why A wins", 16, "#ffffff", "bold"),
        text(legend_x, legend_y + 194, "• two device-free M2 service corridors", 12),
        text(legend_x, legend_y + 216, "• clocks do not share a vertical bank with outputs", 12),
        text(legend_x, legend_y + 238, "• signal, tail bias, and reference now have owned paths", 12),
        text(legend_x, legend_y + 260, "• P/N load tails and pad paths are analytically equal", 12),
        text(legend_x, legend_y + 300, "Explicit cost", 16, "#ffffff", "bold"),
        text(legend_x, legend_y + 324, "Column pitch: 5.20 → 6.96 µm", 12, "#fbbf24"),
        text(legend_x, legend_y + 346, "Selector, dummies, guard, and load placement reopen.", 12, "#fbbf24"),
        text(legend_x, legend_y + 368, "Mismatch geometry must be re-qualified before signoff.", 12, "#fbbf24"),
        text(legend_x, legend_y + 418, f"Decision: {selected}", 15, "#4ade80", "bold"),
        text(legend_x, legend_y + 442, "Next gate: exact one-row feasibility, then full channel.", 13, "#dbeafe"),
        '</svg>',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(pieces) + "\n", encoding="utf-8")


def render_tile(data: dict[str, Any], output: Path) -> None:
    candidate = data["candidates"][data["decision"]["selected"]]
    scale = 3.0
    die_w, die_h = 334.88, 225.76
    margin = 34
    canvas_w = margin * 2 + die_w * scale
    canvas_h = margin * 2 + die_h * scale

    def sx(value: float) -> float:
        return margin + value * scale

    def sy(value: float) -> float:
        return margin + (die_h - value) * scale

    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}">',
        rect(0, 0, canvas_w, canvas_h, "#0b1018"),
        rect(sx(0), sy(die_h), die_w * scale, die_h * scale, "#111827", "#94a3b8"),
        text(sx(6), sy(218), "V3 selected full-tile routing skeleton", 21, "#ffffff", "bold"),
    ]
    origins = data["fixed_constraints"]["channel_origins_x_um"]
    for index, origin in enumerate(origins):
        active = candidate["active_array_bbox"]
        pieces.append(rect(sx(origin + active[0]), sy(8 + active[3]), (active[2]-active[0])*scale, (active[3]-active[1])*scale, COLORS["device"], "#9aabba", 0.42, 2))
        for x_value in candidate["service_corridors"]["output_left"]["spines"].values():
            pieces.append(f'<line x1="{sx(origin+x_value):.2f}" y1="{sy(8+7.7):.2f}" x2="{sx(origin+x_value):.2f}" y2="{sy(8+108.8):.2f}" stroke="{COLORS["output"]}" stroke-width="2.2"/>')
        for x_value in candidate["service_corridors"]["analog_right"]["spines"].values():
            pieces.append(f'<line x1="{sx(origin+x_value):.2f}" y1="{sy(8+7.7):.2f}" x2="{sx(origin+x_value):.2f}" y2="{sy(8+112.0):.2f}" stroke="{COLORS["analog"]}" stroke-width="1.8"/>')
        for x_value in candidate["phase_distribution"]["internal_g1_trunks_x_um"] + candidate["phase_distribution"]["side_bank_trunks_x_um"]:
            pieces.append(f'<line x1="{sx(origin+x_value):.2f}" y1="{sy(8+20.7):.2f}" x2="{sx(origin+x_value):.2f}" y2="{sy(8+112.0):.2f}" stroke="{COLORS["phase"]}" stroke-width="1.4" opacity="0.85"/>')
        pieces.append(text(sx(origin + 9.66), sy(10), f"CH{3-index}", 11, "#ffffff", "bold", "middle"))

    support = candidate["support_band_global"]
    bbox = support["bbox"]
    pieces.append(rect(sx(bbox[0]), sy(bbox[3]), (bbox[2]-bbox[0])*scale, (bbox[3]-bbox[1])*scale, COLORS["support"], COLORS["support"], 0.10, 3))
    for x_value in support["compact_input_bias_resistor_centers_x_um"]:
        y0, y1 = support["compact_input_bias_bbox_y_um"]
        pieces.append(rect(sx(x_value-1.005), sy(y1), 2.01*scale, (y1-y0)*scale, COLORS["support"], "#fb923c", 0.72, 2))
    for side, center in support["output_load_centers_um"].items():
        pieces.append(rect(sx(center[0]-1.535), sy(center[1]+8.715), 3.07*scale, 17.43*scale, "#facc15", "#fde68a", 0.62, 2))
        pieces.append(text(sx(center[0]), sy(center[1]), f"LOAD {side.upper()}", 8, "#111827", "bold", "middle"))

    selector_y0, selector_y1 = candidate["selector_and_global_phase"]["selector_band_global_y_um"]
    pieces.append(rect(sx(84), sy(selector_y1), 79*scale, (selector_y1-selector_y0)*scale, COLORS["selector"], COLORS["selector"], 0.17, 3))
    pieces.append(text(sx(123.5), sy(160), "four rebuilt selectors", 13, "#fecaca", "bold", "middle"))
    phase_y0, phase_y1 = candidate["selector_and_global_phase"]["phase_tree_band_global_y_um"]
    pieces.append(rect(sx(84), sy(phase_y1), 96*scale, (phase_y1-phase_y0)*scale, COLORS["phase"], COLORS["phase"], 0.14, 3))
    pieces.append(text(sx(132), sy(194), "balanced global quadrature tree", 13, "#e9d5ff", "bold", "middle"))

    # Output H-tree intent, drawn as two nearby colours for the pair.
    out = candidate["global_output_collection"]
    for side, roots, colour, dy in (
        ("p", out["p_channel_roots_x_um"], "#38bdf8", 0.0),
        ("n", out["n_channel_roots_x_um"], "#0ea5e9", -1.1),
    ):
        y_leaf = out["channel_root_y_um"] + dy
        pairs = [(roots[0]+roots[1])/2, (roots[2]+roots[3])/2]
        root = sum(roots)/4
        for x_value in roots:
            pair = pairs[0] if x_value < root else pairs[1]
            pieces.append(f'<path d="M {sx(x_value):.2f},{sy(y_leaf):.2f} V {sy(y_leaf+1.4):.2f} H {sx(pair):.2f}" fill="none" stroke="{colour}" stroke-width="1.8"/>')
        pieces.append(f'<path d="M {sx(pairs[0]):.2f},{sy(y_leaf+1.4):.2f} V {sy(y_leaf+2.8):.2f} H {sx(pairs[1]):.2f}" fill="none" stroke="{colour}" stroke-width="1.8"/>')
        load_x = out["load_centers_x_um"][side]
        pieces.append(f'<line x1="{sx(root):.2f}" y1="{sy(y_leaf+2.8):.2f}" x2="{sx(load_x):.2f}" y2="{sy(y_leaf+2.8):.2f}" stroke="{colour}" stroke-width="1.8"/>')

    pieces += [
        text(sx(190), sy(150), "quiet bias / decoupling", 14, "#a7f3d0", "bold"),
        text(sx(190), sy(142), "static control: right side", 12, "#aebdd0"),
        text(sx(190), sy(132), "Metal 5: no signal use", 12, "#aebdd0"),
        text(sx(190), sy(122), "No U-turns / stubs / orphan vias", 12, "#aebdd0"),
        '</svg>',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(pieces) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--compare", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--tile", type=Path, default=DEFAULT_TILE)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    render_compare(data, args.compare)
    render_tile(data, args.tile)
    print(args.compare)
    print(args.tile)


if __name__ == "__main__":
    main()
