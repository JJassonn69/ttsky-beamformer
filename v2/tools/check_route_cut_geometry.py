#!/usr/bin/env python3
"""Fast SKY130 cut-size and local enclosure checks for route overlays.

These checks intentionally mirror the small subset of the independent
KLayout deck used by the handoff generators.  They catch the common mistake
of writing a Magic contact-paint box directly as one oversized GDS cut.
"""

from __future__ import annotations

from typing import Any


TOL = 1e-9
CUT_SIZE_UM = 0.20


def _margins(landing: list[float], cut: list[float]) -> tuple[float, ...] | None:
    lx0, ly0, lx1, ly1 = map(float, landing)
    cx0, cy0, cx1, cy1 = map(float, cut)
    if lx0 > cx0 + TOL or ly0 > cy0 + TOL or lx1 < cx1 - TOL or ly1 < cy1 - TOL:
        return None
    return cx0 - lx0, lx1 - cx1, cy0 - ly0, ly1 - cy1


def _has_enclosure(
    shapes: list[dict[str, Any]], via: dict[str, Any], layer: str,
    basic: float, adjacent: float | None = None,
) -> bool:
    candidates = (
        item for item in shapes
        if item["net"] == via["net"] and item["layer"] == layer
    )
    for item in candidates:
        margins = _margins(item["bbox_um"], via["bbox_um"])
        if margins is None or min(margins) < basic - TOL:
            continue
        if adjacent is None:
            return True
        left, right, bottom, top = margins
        # The larger enclosure must occur on two opposite edges so no corner
        # has two adjacent edges below the projection rule.
        if min(left, right) >= adjacent - TOL or min(bottom, top) >= adjacent - TOL:
            return True
    return False


def cut_geometry_errors(shapes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    rules = {
        "via2": (("metal2", .040, .085), ("metal3", .065, None)),
        "via3": (("metal3", .060, .090), ("metal4", .065, None)),
    }
    for via in (item for item in shapes if item["layer"] in rules):
        x0, y0, x1, y1 = map(float, via["bbox_um"])
        width, height = x1 - x0, y1 - y0
        if abs(width - CUT_SIZE_UM) > TOL or abs(height - CUT_SIZE_UM) > TOL:
            errors.append(
                f"{via['id']} is {width:.3f}x{height:.3f} um; "
                f"{via['layer']} must be one {CUT_SIZE_UM:.2f}x{CUT_SIZE_UM:.2f} um cut"
            )
        for layer, basic, adjacent in rules[via["layer"]]:
            if not _has_enclosure(shapes, via, layer, basic, adjacent):
                errors.append(
                    f"{via['id']} lacks legal {layer} enclosure for {via['layer']}"
                )
    duplicates: set[tuple[Any, ...]] = set()
    seen: set[tuple[Any, ...]] = set()
    for item in shapes:
        key = (item["net"], item["layer"], *map(float, item["bbox_um"]))
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    for net, layer, *_bbox in sorted(duplicates):
        errors.append(f"{net} contains a redundant identical {layer} rectangle")
    return errors

