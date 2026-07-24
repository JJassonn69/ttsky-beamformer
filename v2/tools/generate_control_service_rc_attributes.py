#!/usr/bin/env python3
"""Generate final-chip Magic drive attributes for control, analog, and power."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .generate_rc_force_attributes import (
        DRIVE_ONLY_RE,
        EXTERNAL_UNDRIVEN_RE,
        DEFAULT_ROUTES,
        collect_labels,
    )
except ImportError:  # direct script execution
    from generate_rc_force_attributes import (
        DRIVE_ONLY_RE,
        EXTERNAL_UNDRIVEN_RE,
        DEFAULT_ROUTES,
        collect_labels,
    )


EXTERNAL_INPUTS = {"cfg_clk", "cfg_latch", "clk", "rst_n"}
EXTERNAL_SUPPLIES = {"VDPWR", "VGND"}


def generate(
    service_geometry: dict[str, Any],
    power_geometry: dict[str, Any],
    analog_routes: list[Path],
    output: Path,
) -> int:
    labels = {
        item["net"]: item for item in service_geometry["labels"]
        if item["net"] in EXTERNAL_INPUTS
    }
    if set(labels) != EXTERNAL_INPUTS:
        raise ValueError(
            f"external control labels {sorted(labels)} != {sorted(EXTERNAL_INPUTS)}"
        )
    power_labels = {
        item["net"]: item for item in power_geometry["labels"]
        if item["net"] in EXTERNAL_SUPPLIES
    }
    if set(power_labels) != EXTERNAL_SUPPLIES:
        raise ValueError(
            f"external supply labels {sorted(power_labels)} != "
            f"{sorted(EXTERNAL_SUPPLIES)}"
        )
    analog_labels = collect_labels(analog_routes)
    lines = [
        "# Generated; temporary RC-extraction attributes only; not manufactured.",
    ]
    for net in sorted(labels):
        item = labels[net]
        x, y = map(float, item["point_um"])
        layer = str(item["layer"]).replace("metal", "met")
        lines.extend((
            f"# force external input {net}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{res:force@}} FreeSans 0.10u -{layer}",
            f"label {{res:drive@}} FreeSans 0.10u -{layer}",
        ))
    for net in sorted(power_labels):
        item = power_labels[net]
        x, y = map(float, item["point_um"])
        layer = str(item["layer"]).replace("metal", "met")
        lines.extend((
            f"# force external supply {net}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{res:force@}} FreeSans 0.10u -{layer}",
            f"label {{res:drive@}} FreeSans 0.10u -{layer}",
        ))
    for net, x1, y1, x2, y2, layer in analog_labels:
        lines.extend((
            f"# force critical analog route {net}",
            f"box {x1}um {y1}um {x2}um {y2}um",
        ))
        if EXTERNAL_UNDRIVEN_RE.match(net):
            lines.append(f"label {{res:force@}} FreeSans 0.10u -{layer}")
        if EXTERNAL_UNDRIVEN_RE.match(net) or DRIVE_ONLY_RE.match(net):
            lines.append(f"label {{res:drive@}} FreeSans 0.10u -{layer}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(labels) + len(power_labels) + len(analog_labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geometry", type=Path,
        default=Path("build/v2/control_routing/service_geometry.json"),
    )
    parser.add_argument(
        "--power-geometry", type=Path,
        default=Path("build/v2/control_power/control_power_geometry.json"),
    )
    parser.add_argument(
        "--analog-routes", nargs="*", type=Path, default=list(DEFAULT_ROUTES),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v2/control_routing/control_service_rc/force_attributes.tcl"),
    )
    args = parser.parse_args()
    count = generate(
        json.loads(args.geometry.read_text()),
        json.loads(args.power_geometry.read_text()),
        args.analog_routes,
        args.output,
    )
    print(f"{args.output}: annotated {count} control/analog/power drive points")


if __name__ == "__main__":
    main()
