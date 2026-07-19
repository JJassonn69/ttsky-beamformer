#!/usr/bin/env python3
"""Reject generated top-level geometry that overlaps across logical nets."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

LAYERS = r"metal[1-4]|locali|via[1-3]|viali"


@dataclass(frozen=True)
class Shape:
    x1: float
    y1: float
    x2: float
    y2: float
    net: str
    line: int


def overlaps(a: Shape, b: Shape) -> bool:
    return min(a.x2, b.x2) >= max(a.x1, b.x1) and min(a.y2, b.y2) >= max(a.y1, b.y1)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "build/layout/route.tcl")
    shapes: dict[str, list[Shape]] = defaultdict(list)
    net: str | None = None
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        for pattern in (r"# horizontal net track: (.+)", r"# .* -> (.+)"):
            match = re.match(pattern, line)
            if match:
                net = match.group(1)
        match = re.match(
            rf"paint_rect ({LAYERS}) ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+)",
            line,
        )
        if match and net is not None:
            layer = match.group(1)
            x1, y1, x2, y2 = map(float, match.groups()[1:])
            shapes[layer].append(Shape(x1, y1, x2, y2, net, line_number))

    errors: list[str] = []
    for layer, layer_shapes in shapes.items():
        for index, first in enumerate(layer_shapes):
            for second in layer_shapes[index + 1 :]:
                if first.net != second.net and overlaps(first, second):
                    errors.append(
                        f"{layer}: {first.net} line {first.line} overlaps "
                        f"{second.net} line {second.line}"
                    )
    if errors:
        print("Generated route contains cross-net overlaps:")
        print("\n".join(errors[:50]))
        raise SystemExit(1)
    print(f"Generated-route overlap audit passed ({sum(map(len, shapes.values()))} shapes)")


if __name__ == "__main__":
    main()
