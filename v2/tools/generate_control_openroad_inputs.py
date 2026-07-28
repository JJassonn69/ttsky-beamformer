#!/usr/bin/env python3
"""Generate complete OpenROAD/TritonRoute jobs for V2 control internals.

The fixed production placement is preserved.  Global, phase, and trim banks
are routed in one bounded job so cross-bank control and service trees are
optimized with all local nets visible at once.  Every standard-cell pin on
internal, trim, quadrature, direct-boundary, and service nets is owned by
OpenROAD, with no hand-authored pin-access fallback.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from generate_control_qrouter_inputs import generate as generate_router_inputs


def tcl_path(path: Path) -> str:
    value = str(path.resolve())
    if "{" in value or "}" in value:
        raise ValueError(f"Tcl path contains a brace: {value}")
    return "{" + value + "}"


def make_route_tcl(
    technology_lef: Path,
    cell_lef: Path,
    input_def: Path,
    output_dir: Path,
) -> str:
    output_dir = output_dir.resolve()
    routed_def = output_dir / "routed.def"
    routed_db = output_dir / "routed.odb"
    guide = output_dir / "route.guide"
    congestion = output_dir / "congestion.rpt"
    drc = output_dir / "detailed_route_drc.rpt"
    coverage = output_dir / "guide_coverage.csv"
    wire = output_dir / "wire_length.csv"
    return "\n".join((
        "# Generated fixed-placement production route for V2 control internals",
        "set_thread_count 4",
        f"read_lef {tcl_path(technology_lef)}",
        f"read_lef {tcl_path(cell_lef)}",
        f"read_def {tcl_path(input_def)}",
        # li1 remains available as foundry-defined cell-pin geometry, but the
        # global routing grid starts on met1.  TritonRoute creates the legal
        # mcon escape from LI ports during pin-access analysis; FastRoute does
        # not accept li1 as a global-routing layer in the SKY130 HD tech LEF.
        "set_routing_layers -signal met1-met4 -clock met1-met4",
        "set_global_routing_layer_adjustment met1 0.20",
        "set_global_routing_layer_adjustment met2-met4 0.10",
        f"global_route -guide_file {tcl_path(guide)} -congestion_iterations 100 "
        f"-congestion_report_file {tcl_path(congestion)} -verbose",
        f"detailed_route -output_drc {tcl_path(drc)} "
        f"-output_guide_coverage {tcl_path(coverage)} -droute_end_iter 64 "
        "-clean_patches -verbose 1",
        f"report_wire_length -net * -global_route -detailed_route -verbose "
        f"-file {tcl_path(wire)}",
        f"write_def {tcl_path(routed_def)}",
        f"write_db {tcl_path(routed_db)}",
        "exit",
        "",
    ))


def generate(
    placement: dict[str, Any],
    allocation: dict[str, Any],
    power_geometry: dict[str, Any],
    power_plan: dict[str, Any],
    integration: dict[str, Any],
    technology_lef: Path,
    cell_lef: Path,
    output_dir: Path,
) -> dict[str, Any]:
    report = generate_router_inputs(
        placement,
        allocation,
        power_geometry,
        power_plan,
        integration,
        technology_lef,
        cell_lef,
        output_dir,
        backend="openroad",
    )
    for job in report["jobs"]:
        job_dir = output_dir / job["region"]
        job_dir.mkdir(parents=True, exist_ok=True)
        script = job_dir / "route.tcl"
        script.write_text(make_route_tcl(
            technology_lef,
            cell_lef,
            Path(job["def"]),
            job_dir,
        ), encoding="utf-8")
        job["script"] = str(script)
        job["outputs"] = {
            "def": str(job_dir / "routed.def"),
            "database": str(job_dir / "routed.odb"),
            "guide": str(job_dir / "route.guide"),
            "drc": str(job_dir / "detailed_route_drc.rpt"),
            "guide_coverage": str(job_dir / "guide_coverage.csv"),
            "wire_length": str(job_dir / "wire_length.csv"),
        }
    (output_dir / "openroad_jobs.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement", type=Path, default=Path("build/v2/control_placement/control_placement.json"))
    parser.add_argument("--allocation", type=Path, default=Path("build/v2/control_routing/control_route_allocation.json"))
    parser.add_argument("--power-geometry", type=Path, default=Path("build/v2/control_power/control_power_geometry.json"))
    parser.add_argument("--power-plan", type=Path, default=Path("v2/layout/control_power_plan.json"))
    parser.add_argument("--integration", type=Path, default=Path("v2/layout/integration_plan.json"))
    parser.add_argument("--technology-lef", type=Path, required=True)
    parser.add_argument("--cell-lef", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("build/v2/control_routing/openroad"))
    args = parser.parse_args()
    report = generate(
        json.loads(args.placement.read_text(encoding="utf-8")),
        json.loads(args.allocation.read_text(encoding="utf-8")),
        json.loads(args.power_geometry.read_text(encoding="utf-8")),
        json.loads(args.power_plan.read_text(encoding="utf-8")),
        json.loads(args.integration.read_text(encoding="utf-8")),
        args.technology_lef,
        args.cell_lef,
        args.output_dir,
    )
    print(json.dumps({
        "status": report["status"],
        "backend": report["backend"],
        "total_internal_nets": report["total_internal_nets"],
        "router_nets": report["router_net_count"],
        "jobs": [
            {"region": item["region"], "nets": item["net_count"]}
            for item in report["jobs"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
