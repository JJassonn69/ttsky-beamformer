#!/usr/bin/env python3
"""Generate temporary drive attributes for full-chip distributed-RC extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from generate_rc_force_attributes import (
        DEFAULT_ROUTES,
        DRIVE_ONLY_RE,
        EXTERNAL_UNDRIVEN_RE,
        FORCE_ONLY_RE,
        collect_labels,
    )
except ModuleNotFoundError:
    from v2.tools.generate_rc_force_attributes import (
        DEFAULT_ROUTES,
        DRIVE_ONLY_RE,
        EXTERNAL_UNDRIVEN_RE,
        FORCE_ONLY_RE,
        collect_labels,
    )


def generate(
    allocation: dict[str, Any],
    jobs: dict[str, Any],
    power_geometry: dict[str, Any],
    control_geometry: dict[str, Any],
    analog_routes: list[Path],
    output: Path,
) -> dict[str, int]:
    external_nets = {
        item["net"] for item in allocation["nets"]
        if any(endpoint["kind"] == "external_top_pin"
               for endpoint in item["endpoints"])
    }
    external_points: dict[str, tuple[float, float, str]] = {}
    for job in jobs["jobs"]:
        ox, oy = map(float, job["coordinate_offset_um"])
        for pin in job["top_pins"].values():
            net = pin["net"]
            if net not in external_nets:
                continue
            if net in external_points:
                raise ValueError(f"{net}: multiple router-owned external pins")
            x, y = map(float, pin["point_um"])
            external_points[net] = (x + ox, y + oy, pin["layer"])
    if set(external_points) != external_nets:
        raise ValueError(
            f"external RC points {sorted(external_points)} != {sorted(external_nets)}"
        )

    power_points = {
        item["net"]: item for item in power_geometry["labels"]
        if item["net"] in {"VDPWR", "VGND"}
    }
    if set(power_points) != {"VDPWR", "VGND"}:
        raise ValueError("both external supply labels are required for final RCX")

    lines = [
        "# Generated; temporary full-chip RC attributes only; not manufactured.",
    ]
    for net in sorted(external_points):
        x, y, layer = external_points[net]
        lines.extend((
            f"# force external input {net}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{res:force@}} FreeSans 0.10u -{layer}",
            f"label {{res:drive@}} FreeSans 0.10u -{layer}",
        ))
    for net in sorted(power_points):
        item = power_points[net]
        x, y = map(float, item["point_um"])
        layer = str(item["layer"]).replace("metal", "met")
        lines.extend((
            f"# force external supply {net}",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{res:force@}} FreeSans 0.10u -{layer}",
            f"label {{res:drive@}} FreeSans 0.10u -{layer}",
        ))

    # OpenROAD emits one deterministic Rxxx label on every routed control net.
    # Anchor distributed-resistance extraction at those exact track locations,
    # rather than relying only on a top-pin label that can sit on a prunable
    # access branch.  ``res:force@`` affects only Magic's temporary extraction
    # cell: it adds no manufactured geometry and does not invent a driver for
    # device-driven internal nets.
    control_labels = control_geometry["labels"]
    if len(control_labels) != len(control_geometry["label_net_map"]):
        raise ValueError("control geometry must contain one point per Rxxx label")
    seen_control_labels: set[str] = set()
    for item in sorted(control_labels, key=lambda value: value["gds_label"]):
        label = str(item["gds_label"])
        if label in seen_control_labels:
            raise ValueError(f"duplicate control route label {label}")
        seen_control_labels.add(label)
        if control_geometry["label_net_map"].get(label) != item["net"]:
            raise ValueError(f"{label}: label/net map disagrees with geometry")
        x, y = map(float, item["point_um"])
        layer = str(item["layer"]).replace("metal", "met")
        lines.extend((
            f"# retain routed control mesh {label} ({item['net']})",
            f"box {x:.6f}um {y:.6f}um {x:.6f}um {y:.6f}um",
            f"label {{res:force@}} FreeSans 0.10u -{layer}",
        ))
    analog_labels = collect_labels(analog_routes)
    for net, x1, y1, x2, y2, layer in analog_labels:
        lines.extend((
            f"# force critical analog route {net}",
            f"box {x1}um {y1}um {x2}um {y2}um",
        ))
        if EXTERNAL_UNDRIVEN_RE.match(net) or FORCE_ONLY_RE.match(net):
            lines.append(f"label {{res:force@}} FreeSans 0.10u -{layer}")
        if (
            EXTERNAL_UNDRIVEN_RE.match(net)
            or DRIVE_ONLY_RE.match(net)
            or FORCE_ONLY_RE.match(net)
        ):
            lines.append(f"label {{res:drive@}} FreeSans 0.10u -{layer}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "external_inputs": len(external_points),
        "external_supplies": len(power_points),
        "control_routes": len(control_labels),
        "analog_routes": len(analog_labels),
        "total_points": (
            len(external_points) + len(power_points)
            + len(control_labels) + len(analog_labels)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allocation", type=Path,
        default=Path("build/v2/control_routing/control_route_allocation.json"),
    )
    parser.add_argument(
        "--jobs", type=Path,
        default=Path("build/v2/control_routing/openroad/openroad_jobs.json"),
    )
    parser.add_argument(
        "--power-geometry", type=Path,
        default=Path("build/v2/control_power/control_power_geometry.json"),
    )
    parser.add_argument(
        "--control-geometry", type=Path,
        default=Path("build/v2/control_routing/openroad_route_geometry.json"),
    )
    parser.add_argument(
        "--analog-routes", nargs="*", type=Path, default=list(DEFAULT_ROUTES),
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/v2/control_routing/final_rc/force_attributes.tcl"),
    )
    args = parser.parse_args()
    counts = generate(
        json.loads(args.allocation.read_text()),
        json.loads(args.jobs.read_text()),
        json.loads(args.power_geometry.read_text()),
        json.loads(args.control_geometry.read_text()),
        args.analog_routes,
        args.output,
    )
    print(json.dumps(counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
