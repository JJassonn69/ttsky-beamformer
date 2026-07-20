#!/usr/bin/env python3
"""Render the signed-off hierarchical GDS without depending on a GUI viewer.

The renderer intentionally consumes the release GDS (not Magic source) so the
documentation images show the exact geometry submitted to fabrication.
"""

from __future__ import annotations

import argparse
import math
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


@dataclass
class Reference:
    name: str
    origin: tuple[int, int]
    reflected: bool = False
    magnification: float = 1.0
    angle: float = 0.0


@dataclass
class Structure:
    polygons: list[tuple[tuple[int, int], list[tuple[int, int]]]] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)


# Human-readable layer names and a bottom-to-top drawing order for SKY130.
LAYERS = {
    (235, 4): ("tile boundary", (118, 129, 151, 42)),
    (64, 20): ("n-well", (73, 123, 255, 60)),
    (94, 20): ("p+ implant", (255, 118, 137, 54)),
    (93, 44): ("n+ implant", (90, 181, 255, 54)),
    (65, 20): ("diffusion", (76, 222, 128, 112)),
    (65, 44): ("substrate/well tap", (84, 239, 174, 118)),
    (95, 20): ("poly keepout / NPC", (239, 194, 77, 42)),
    (66, 20): ("polysilicon", (255, 100, 83, 132)),
    (66, 13): ("poly terminal", (255, 146, 113, 170)),
    (79, 20): ("ultra-high-R poly marker", (253, 186, 116, 94)),
    (86, 20): ("resistor marker", (251, 191, 36, 94)),
    (67, 20): ("local interconnect (LI1)", (214, 214, 214, 116)),
    (66, 44): ("licon/contact", (255, 245, 157, 225)),
    (67, 44): ("mcon", (255, 233, 96, 235)),
    (68, 20): ("metal 1", (75, 213, 238, 118)),
    (68, 44): ("via 1", (218, 247, 166, 235)),
    (69, 20): ("metal 2", (192, 132, 252, 116)),
    (69, 44): ("via 2", (244, 114, 182, 235)),
    (70, 20): ("metal 3", (251, 146, 60, 116)),
    (89, 44): ("MIM capacitor plate (capm)", (250, 204, 21, 135)),
    (70, 44): ("via 3", (253, 224, 71, 240)),
    (71, 20): ("metal 4", (248, 113, 113, 120)),
    (71, 16): ("metal 4 pin", (255, 168, 168, 170)),
}


def real8(data: bytes) -> float:
    if data == b"\0" * 8:
        return 0.0
    sign = -1.0 if data[0] & 0x80 else 1.0
    exponent = (data[0] & 0x7F) - 64
    mantissa = int.from_bytes(data[1:], "big") / float(1 << 56)
    return sign * mantissa * (16.0**exponent)


def text_value(data: bytes) -> str:
    return data.rstrip(b"\0").decode("ascii")


def parse_gds(path: Path) -> tuple[dict[str, Structure], str, float]:
    structures: dict[str, Structure] = {}
    current: Structure | None = None
    current_name = ""
    element: dict[str, object] | None = None
    meters_per_db = 1e-9
    last_structure = ""

    raw = path.read_bytes()
    offset = 0
    while offset < len(raw):
        length, record_type, data_type = struct.unpack(">HBB", raw[offset : offset + 4])
        if length < 4 or offset + length > len(raw):
            raise ValueError(f"invalid GDS record at byte {offset}")
        data = raw[offset + 4 : offset + length]
        offset += length

        if record_type == 0x03 and len(data) >= 16:  # UNITS
            meters_per_db = real8(data[8:16])
        elif record_type == 0x05:  # BGNSTR
            current = Structure()
            current_name = ""
        elif record_type == 0x06:  # STRNAME
            current_name = text_value(data)
            last_structure = current_name
        elif record_type in (0x08, 0x0A):  # BOUNDARY or SREF
            element = {"type": record_type, "layer": 0, "datatype": 0}
        elif record_type == 0x0D and element is not None:  # LAYER
            element["layer"] = struct.unpack(">h", data)[0]
        elif record_type == 0x0E and element is not None:  # DATATYPE
            element["datatype"] = struct.unpack(">h", data)[0]
        elif record_type == 0x10 and element is not None:  # XY
            values = struct.unpack(f">{len(data) // 4}i", data)
            element["xy"] = list(zip(values[0::2], values[1::2]))
        elif record_type == 0x12 and element is not None:  # SNAME
            element["name"] = text_value(data)
        elif record_type == 0x1A and element is not None:  # STRANS
            element["reflected"] = bool(struct.unpack(">H", data)[0] & 0x8000)
        elif record_type == 0x1B and element is not None:  # MAG
            element["magnification"] = real8(data)
        elif record_type == 0x1C and element is not None:  # ANGLE
            element["angle"] = real8(data)
        elif record_type == 0x11 and element is not None and current is not None:  # ENDEL
            xy = element.get("xy", [])
            if element["type"] == 0x08 and len(xy) >= 3:
                current.polygons.append(
                    ((int(element["layer"]), int(element["datatype"])), list(xy))
                )
            elif element["type"] == 0x0A and xy:
                current.references.append(
                    Reference(
                        name=str(element["name"]),
                        origin=xy[0],
                        reflected=bool(element.get("reflected", False)),
                        magnification=float(element.get("magnification", 1.0)),
                        angle=float(element.get("angle", 0.0)),
                    )
                )
            element = None
        elif record_type == 0x07 and current is not None:  # ENDSTR
            structures[current_name] = current
            current = None

    return structures, last_structure, meters_per_db * 1e6


Matrix = tuple[float, float, float, float, float, float]


def compose(parent: Matrix, child: Matrix) -> Matrix:
    a, b, c, d, tx, ty = parent
    e, f, g, h, ux, uy = child
    return (
        a * e + b * g,
        a * f + b * h,
        c * e + d * g,
        c * f + d * h,
        a * ux + b * uy + tx,
        c * ux + d * uy + ty,
    )


def reference_matrix(ref: Reference) -> Matrix:
    theta = math.radians(ref.angle)
    cs, sn = math.cos(theta), math.sin(theta)
    sy = -ref.magnification if ref.reflected else ref.magnification
    sx = ref.magnification
    return (cs * sx, -sn * sy, sn * sx, cs * sy, ref.origin[0], ref.origin[1])


def transform_point(matrix: Matrix, point: tuple[int, int]) -> tuple[float, float]:
    a, b, c, d, tx, ty = matrix
    x, y = point
    return a * x + b * y + tx, c * x + d * y + ty


def flatten(
    structures: dict[str, Structure], top: str
) -> list[tuple[tuple[int, int], list[tuple[float, float]]]]:
    output: list[tuple[tuple[int, int], list[tuple[float, float]]]] = []

    def visit(name: str, matrix: Matrix, ancestry: tuple[str, ...]) -> None:
        if name in ancestry:
            raise ValueError(f"recursive GDS hierarchy: {' -> '.join(ancestry + (name,))}")
        structure = structures[name]
        for layer, polygon in structure.polygons:
            output.append((layer, [transform_point(matrix, point) for point in polygon]))
        for ref in structure.references:
            visit(ref.name, compose(matrix, reference_matrix(ref)), ancestry + (name,))

    visit(top, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), ())
    return output


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render(
    polygons: list[tuple[tuple[int, int], list[tuple[float, float]]]],
    db_um: float,
    output: Path,
    crop_um: tuple[float, float, float, float],
    title: str,
    size: tuple[int, int],
    annotations: list[tuple[tuple[float, float, float, float], str]],
) -> None:
    scale_factor = 2
    width, height = size[0] * scale_factor, size[1] * scale_factor
    legend_width = 315 * scale_factor
    header_height = 60 * scale_factor
    margin = 28 * scale_factor
    plot_width = width - legend_width - 3 * margin
    plot_height = height - header_height - 2 * margin
    x0, y0, x1, y1 = crop_um
    scale = min(plot_width / (x1 - x0), plot_height / (y1 - y0))
    draw_width = (x1 - x0) * scale
    draw_height = (y1 - y0) * scale
    plot_left = margin + (plot_width - draw_width) / 2
    plot_top = header_height + margin + (plot_height - draw_height) / 2

    image = Image.new("RGBA", (width, height), (12, 18, 29, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = load_font(17 * scale_factor)
    small = load_font(13 * scale_factor)
    title_font = load_font(24 * scale_factor, bold=True)
    draw.text((margin, 14 * scale_factor), title, fill=(240, 244, 252, 255), font=title_font)
    draw.text(
        (margin, 42 * scale_factor),
        f"Signed-off GDS geometry | view {x0:g},{y0:g} to {x1:g},{y1:g} um",
        fill=(158, 171, 194, 255),
        font=small,
    )

    def to_pixel(point: tuple[float, float]) -> tuple[float, float]:
        x_um, y_um = point[0] * db_um, point[1] * db_um
        return plot_left + (x_um - x0) * scale, plot_top + (y1 - y_um) * scale

    ordered = [layer for layer in LAYERS if any(item[0] == layer for item in polygons)]
    for layer in ordered:
        name, color = LAYERS[layer]
        del name
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(overlay, "RGBA")
        for polygon_layer, points in polygons:
            if polygon_layer != layer:
                continue
            px = [to_pixel(point) for point in points]
            if max(p[0] for p in px) < plot_left or min(p[0] for p in px) > plot_left + draw_width:
                continue
            if max(p[1] for p in px) < plot_top or min(p[1] for p in px) > plot_top + draw_height:
                continue
            layer_draw.polygon(px, fill=color, outline=(color[0], color[1], color[2], min(255, color[3] + 70)))
        image = Image.alpha_composite(image, overlay)

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle(
        (plot_left, plot_top, plot_left + draw_width, plot_top + draw_height),
        outline=(181, 195, 219, 175),
        width=2 * scale_factor,
    )
    for box, label in annotations:
        ax0 = plot_left + (box[0] - x0) * scale
        ay0 = plot_top + (y1 - box[3]) * scale
        ax1 = plot_left + (box[2] - x0) * scale
        ay1 = plot_top + (y1 - box[1]) * scale
        draw.rectangle((ax0, ay0, ax1, ay1), outline=(248, 250, 252, 210), width=2 * scale_factor)
        label_box = draw.textbbox((0, 0), label, font=small)
        label_width = label_box[2] - label_box[0]
        draw.rectangle(
            (ax0, max(plot_top, ay0 - 22 * scale_factor), ax0 + label_width + 12 * scale_factor, ay0),
            fill=(12, 18, 29, 220),
        )
        draw.text((ax0 + 5 * scale_factor, max(plot_top, ay0 - 20 * scale_factor)), label, fill=(248, 250, 252, 255), font=small)

    legend_x = width - legend_width + 18 * scale_factor
    legend_y = header_height + margin
    draw.text((legend_x, legend_y), "Visible layers", fill=(240, 244, 252, 255), font=font)
    legend_y += 34 * scale_factor
    counts = Counter(layer for layer, _ in polygons)
    for layer in reversed(ordered):
        name, color = LAYERS[layer]
        draw.rectangle(
            (legend_x, legend_y + 3 * scale_factor, legend_x + 20 * scale_factor, legend_y + 17 * scale_factor),
            fill=(color[0], color[1], color[2], max(color[3], 150)),
            outline=(230, 235, 245, 180),
        )
        draw.text(
            (legend_x + 29 * scale_factor, legend_y),
            f"{name}  ({counts[layer]})",
            fill=(206, 216, 232, 255),
            font=small,
        )
        legend_y += 25 * scale_factor

    image = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/images"))
    parser.add_argument("--top")
    args = parser.parse_args()

    structures, default_top, db_um = parse_gds(args.gds)
    top = args.top or default_top
    if top not in structures:
        raise SystemExit(f"top cell {top!r} not found")
    polygons = flatten(structures, top)
    counts = Counter(layer for layer, _ in polygons)
    unknown = sorted(layer for layer in counts if layer not in LAYERS)
    if unknown:
        raise SystemExit(f"add names/colors for GDS layers: {unknown}")

    render(
        polygons,
        db_um,
        args.output_dir / "beamformer-gds.png",
        (0.0, 0.0, 161.0, 225.76),
        "TinyTapeout two-channel analog beamformer",
        (1700, 1900),
        [
            ((6, 13, 121, 88), "common-centroid GM and mixer core"),
            ((121, 3, 160, 121), "matched resistors and MIM capacitor"),
            ((8, 182, 157, 225), "clock, phase selection, and output drivers"),
        ],
    )
    render(
        polygons,
        db_um,
        args.output_dir / "beamformer-core-detail.png",
        (5.0, 10.0, 125.0, 90.0),
        "Matching-critical transconductor and switching core",
        (1900, 1250),
        [
            ((9, 15, 121, 48), "A/B; B/A split GM and tail devices"),
            ((8, 54, 112, 84), "A/B; B/A split mixer switches"),
        ],
    )
    render(
        polygons,
        db_um,
        args.output_dir / "beamformer-mim-detail.png",
        (56.0, 85.0, 96.0, 124.0),
        "MIM capacitor and via-3 access detail",
        (1500, 1300),
        [((64, 93, 89, 118), "22 x 22 um MIM capacitor")],
    )
    render(
        polygons,
        db_um,
        args.output_dir / "beamformer-top-boundary-detail.png",
        (50.0, 214.0, 130.0, 225.76),
        "Top-edge TinyTapeout M4 pin clearance",
        (1900, 900),
        [
            ((50.0, 224.76, 130.0, 225.76), "standard top-edge M4 pins"),
            ((50.0, 223.85, 130.0, 224.46), "route ceiling and clearance band"),
        ],
    )
    print(f"top={top} db_unit={db_um:g}um structures={len(structures)} polygons={len(polygons)}")
    for layer, count in sorted(counts.items()):
        print(f"layer={layer[0]}/{layer[1]} name={LAYERS[layer][0]} polygons={count}")


if __name__ == "__main__":
    main()
