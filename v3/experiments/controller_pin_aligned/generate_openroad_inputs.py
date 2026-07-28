#!/usr/bin/env python3
"""Generate Candidate B OpenROAD inputs with pin-ordered north ports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "v3/tools"))

import generate_physical_control_openroad_inputs as base  # noqa: E402


def candidate_boundary_pin_plan(
    mapping: dict[str, Any], offset: list[float], size: list[float]
) -> dict[str, dict[str, Any]]:
    """Use Candidate B's explicit local pin bank, preserving output policy."""

    placement_path = getattr(candidate_boundary_pin_plan, "placement_path", None)
    if placement_path is None:
        raise ValueError("Candidate B placement path was not configured")
    placement = json.loads(Path(placement_path).read_text(encoding="utf-8"))
    interface = placement["boundary_interface"]

    legacy = candidate_boundary_pin_plan.legacy(mapping, offset, size)
    input_nets = {
        net
        for port in mapping["ports"].values()
        if port["direction"] == "input"
        for net in port["nets"]
    }
    ordered = interface["official_pin_order_left_to_right"]
    if set(ordered) != input_nets:
        raise ValueError("Candidate B boundary order differs from mapped inputs")
    local_x = interface["local_pin_x_um"]
    result = {net: pin for net, pin in legacy.items() if net not in input_nets}
    for net in ordered:
        absolute_x = float(local_x[net])
        x = absolute_x - float(offset[0])
        if x <= 0.0 or x >= float(size[0]):
            raise ValueError(f"{net}: Candidate B north port leaves controller")
        routing_class = (
            "clock" if net in {"clk", "cfg_clk"}
            else "reset" if net == "rst_n"
            else "control_input"
        )
        result[net] = {
            "direction": "INPUT",
            "layer": "met2",
            "point_um": [round(x, 6), float(size[1])],
            "rect_um": [-0.15, -0.84, 0.15, 0.0],
            "edge": "north",
            "routing_class": routing_class,
            "candidate_b_absolute_x_um": absolute_x,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--placement",
        type=Path,
        default=ROOT
        / "build/v3/experiments/controller_pin_aligned/physical_control_placement.json",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "build/v3/control_mapping/physical_mapping.json",
    )
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument("--cell-lef", type=Path, required=True)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=ROOT / "build/v3/experiments/controller_pin_aligned/openroad_internal",
    )
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument(
        "--source-gds",
        type=Path,
        default=ROOT
        / "v3/frozen/four_channel_power_integration/v3_four_channel_power_integration.gds",
    )
    parser.add_argument("--source-top", default="v3_four_channel_power_integration")
    parser.add_argument(
        "--power-plan",
        type=Path,
        default=ROOT / "v3/layout/physical_control_power_plan.json",
    )
    args = parser.parse_args()
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be in [1, 32]")

    placement = json.loads(args.placement.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    obstructions = base.frozen_route_obstructions(
        args.source_gds,
        args.source_top,
        list(placement["region"]["bbox_um"]),
    )
    power_plan = json.loads(args.power_plan.read_text(encoding="utf-8"))
    obstructions.extend(
        base.planned_power_contact_obstructions(
            power_plan, list(placement["region"]["bbox_um"])
        )
    )

    candidate_boundary_pin_plan.legacy = base.boundary_pin_plan
    candidate_boundary_pin_plan.placement_path = args.placement
    base.boundary_pin_plan = candidate_boundary_pin_plan
    text, report = base.build_def(placement, mapping, obstructions)

    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "input.def").write_text(text, encoding="utf-8")
    (args.workdir / "route.tcl").write_text(
        base.build_route_tcl(
            args.technology_lef, args.cell_lef, args.workdir, args.threads
        ),
        encoding="utf-8",
    )
    reservation_contract = base.power_reservation_contract(power_plan)
    report["candidate"] = "B"
    report["policy"]["north_ports_follow_official_pin_order"] = True
    report["provenance"] = {
        "placement": str(args.placement),
        "placement_sha256": base.sha256(args.placement),
        "mapping": str(args.mapping),
        "mapping_sha256": base.sha256(args.mapping),
        "technology_lef": str(args.technology_lef),
        "technology_lef_sha256": base.sha256(args.technology_lef),
        "cell_lef": str(args.cell_lef),
        "cell_lef_sha256": base.sha256(args.cell_lef),
        "frozen_source_gds": str(args.source_gds),
        "frozen_source_gds_sha256": base.sha256(args.source_gds),
        "frozen_source_top": args.source_top,
        "power_plan": str(args.power_plan),
        "power_reservation_contract": reservation_contract,
        "power_reservation_contract_sha256": base.canonical_json_sha256(
            reservation_contract
        ),
        "base_generator": "v3/tools/generate_physical_control_openroad_inputs.py",
        "base_generator_sha256": base.sha256(
            ROOT / "v3/tools/generate_physical_control_openroad_inputs.py"
        ),
        "generator": str(Path(__file__).relative_to(ROOT)),
        "generator_sha256": base.sha256(Path(__file__)),
        "candidate_generator": str(Path(__file__).relative_to(ROOT)),
        "candidate_generator_sha256": base.sha256(Path(__file__)),
    }
    (args.workdir / "input_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidate": "B",
                "components": report["component_count"],
                "nets": report["net_count"],
                "pins": report["pin_count"],
                "frozen_route_obstructions": report[
                    "frozen_route_obstruction_count"
                ],
                "planned_power_contact_obstructions": report[
                    "planned_power_contact_obstruction_count"
                ],
                "planned_power_underpass_obstructions": report[
                    "planned_power_underpass_obstruction_count"
                ],
                "metal4_reserved": report["policy"]["metal4_reserved"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
