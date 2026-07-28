#!/usr/bin/env python3
"""Independently audit the shared V3 controller's detailed signal routes.

OpenROAD's zero-DRC result is necessary, but it is not sufficient: a legal
shape can still be a dead branch or miss the intended logical terminal.  This
checker rebuilds every routed net as a conductor graph, adds the qualified LEF
pin polygons, and proves that each graph is one loop-free tree whose leaves
terminate on named pins.  It also freezes the exact route artifacts by hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_control_openroad_routes import (  # noqa: E402
    CONNECTION_RE,
    LAYER_ORDER,
    TOP_PIN_CONNECTION_RE,
    attach_pin_conductors,
    components,
    net_blocks,
    parse_route,
    route_graph,
    sha256,
    wire_report,
)


ALLOWED_CONDUCTOR_LAYERS = {"li1", "met1", "met2", "met3"}
ALLOWED_WIRE_LAYERS = {"met1", "met2", "met3"}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def power_reservation_contract(power_plan: dict[str, Any]) -> dict[str, Any]:
    """Independently select the fields that alter signal-route blockages."""

    region = power_plan["controller_region"]
    underpass = power_plan["ground_finger_underpass"]
    vias = power_plan["via_geometries"]
    return {
        "controller_region": {
            "bbox_um": region["bbox_um"],
            "row_count": region["row_count"],
            "row_height_um": region["row_height_um"],
        },
        "distributed_contact_columns_um": power_plan[
            "distributed_contact_columns_um"
        ],
        "ground_finger_underpass": {
            "layer": underpass["layer"],
            "x_span_um": underpass["x_span_um"],
            "width_um": underpass["width_um"],
        },
        "via_geometries": {
            "M1M2": vias["M1M2"],
            "M2M3": vias["M2M3"],
        },
    }


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate(
    workdir: Path,
    placement_path: Path,
    mapping_path: Path,
    generator_path: Path,
    frozen_source_gds: Path,
    power_plan_path: Path,
) -> dict[str, Any]:
    summary_path = workdir / "input_summary.json"
    routed_def_path = workdir / "routed.def"
    drc_path = workdir / "detailed_route_drc.rpt"
    log_path = workdir / "openroad.log"
    wire_path = workdir / "wire_length.csv"
    guide_path = workdir / "guide_coverage.csv"
    required = (
        summary_path, routed_def_path, drc_path, log_path, wire_path, guide_path,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"missing route artifacts: {missing}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    placement = json.loads(placement_path.read_text(encoding="utf-8"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    provenance = summary.get("provenance", {})
    expected_hashes = {
        "placement_sha256": file_sha256(placement_path),
        "mapping_sha256": file_sha256(mapping_path),
        "generator_sha256": file_sha256(generator_path),
    }
    for name, observed in expected_hashes.items():
        if provenance.get(name) != observed:
            errors.append(f"input provenance {name} differs from the current source")
    if provenance.get("frozen_source_gds_sha256") != file_sha256(frozen_source_gds):
        errors.append("input provenance frozen source GDS differs from the current source")
    current_power_contract = power_reservation_contract(
        json.loads(power_plan_path.read_text(encoding="utf-8"))
    )
    if provenance.get("power_reservation_contract") != current_power_contract:
        errors.append("input provenance power-reservation contract differs")
    if provenance.get("power_reservation_contract_sha256") != canonical_json_sha256(
        current_power_contract
    ):
        errors.append("input provenance power-reservation hash differs")

    if not summary.get("policy", {}).get("metal4_reserved"):
        errors.append("input contract does not reserve M4")
    if summary.get("policy", {}).get("signal_layers") != ["met1", "met2", "met3"]:
        errors.append("input signal-layer contract is not M1-M3")
    if not summary.get("policy", {}).get(
        "frozen_gds_m1_m2_m3_are_explicit_route_obstructions"
    ):
        errors.append("input contract omits frozen-GDS route obstructions")
    obstructions = summary.get("frozen_route_obstructions", [])
    if int(summary.get("frozen_route_obstruction_count", -1)) != len(obstructions):
        errors.append("frozen route obstruction count is inconsistent")
    if obstructions != [{
        "bbox_um": [267.22, 171.36, 268.42, 208.6],
        "kind": "frozen_gds_route_obstruction",
        "layer": "met3",
        "source_rectangle_count": 2,
    }]:
        errors.append("frozen route obstruction set differs from the reviewed source trunk")
    if drc_path.read_bytes():
        errors.append("detailed-route DRC report is not empty")

    log_text = log_path.read_text(encoding="utf-8")
    violation_counts = [
        int(value) for value in re.findall(r"Number of violations = (\d+)", log_text)
    ]
    if not violation_counts or violation_counts[-1] != 0:
        errors.append("final detailed-route violation count is not zero")
    pin_access = [
        int(value) for value in re.findall(r"#stdCellPinNoAp\s*=\s*(\d+)", log_text)
    ]
    if not pin_access or pin_access[-1] != 0:
        errors.append("OpenROAD reports inaccessible standard-cell pins")
    routed_counts = [
        int(value) for value in re.findall(r"Routed nets:\s*(\d+)", log_text)
    ]
    if not routed_counts or routed_counts[-1] != int(summary["net_count"]):
        errors.append("global route did not route every expected net")
    if re.search(r"^\[ERROR|^Error:", log_text, re.MULTILINE):
        errors.append("production OpenROAD log contains a fatal error")

    final_layer_lengths: dict[str, int] = {}
    for layer in ("li1", "met1", "met2", "met3", "met4", "met5"):
        values = [
            int(value) for value in re.findall(
                rf"Total wire length on LAYER {layer} = (\d+) um\.", log_text
            )
        ]
        if values:
            final_layer_lengths[layer] = values[-1]
    if final_layer_lengths.get("met4") != 0 or final_layer_lengths.get("met5") != 0:
        errors.append("production route uses reserved M4 or forbidden M5")

    blocks = net_blocks(routed_def_path.read_text(encoding="utf-8"))
    reports = wire_report(wire_path)
    expected_ids = set(summary["net_ids"])
    if set(blocks) != expected_ids:
        errors.append("routed DEF net IDs differ from the generated input manifest")
    if set(reports) != expected_ids:
        errors.append("wire report net IDs differ from the generated input manifest")

    placement_by_instance = {
        item["instance"]: item for item in placement["placements"]
    }
    mapped_by_instance = {item["instance"]: item for item in mapping["cells"]}
    top_pins = {
        pin_id: summary["boundary_pins"][logical]
        for pin_id, logical in summary["pin_ids"].items()
    }
    job = {
        "coordinate_offset_um": summary["coordinate_offset_um"],
        "component_ids": summary["component_ids"],
        "top_pins": top_pins,
    }
    audited: list[dict[str, Any]] = []
    layer_net_counts: Counter[str] = Counter()
    total_wire = 0.0
    total_vias = 0
    for net_id in sorted(expected_ids):
        if net_id not in blocks or net_id not in reports:
            continue
        logical = summary["net_ids"][net_id]
        block = blocks[net_id]
        connection_text = block.split("+ USE", 1)[0]
        connections = CONNECTION_RE.findall(connection_text)
        top_connections = TOP_PIN_CONNECTION_RE.findall(connection_text)
        pin_count = len(connections) + len(top_connections)
        try:
            segments, vias, layers, extension_adjustment = parse_route(block)
            graph, wire_length = route_graph(segments, vias)
            job_with_block = dict(job)
            job_with_block["current_net_block"] = connection_text
            electrical_graph, memberships = attach_pin_conductors(
                graph,
                connections,
                job_with_block,
                placement_by_instance,
                mapped_by_instance,
                mapping["library"],
            )
        except (KeyError, ValueError) as error:
            errors.append(f"{logical}: {error}")
            continue

        route_groups = components(graph)
        electrical_groups = components(electrical_graph)
        leaves = [node for node, neighbours in graph.items() if len(neighbours) == 1]
        attached = set().union(*memberships.values()) if memberships else set()
        unattached_leaves = [node for node in leaves if node not in attached]
        edge_count = sum(len(neighbours) for neighbours in graph.values()) // 2
        cycle_rank = edge_count - len(graph) + len(route_groups)
        missed_pins = sorted(name for name, nodes in memberships.items() if not nodes)
        unexpected_layers = sorted(layers - ALLOWED_CONDUCTOR_LAYERS)
        unexpected_wire_layers = sorted(
            {segment[0] for segment in segments} - ALLOWED_WIRE_LAYERS
        )
        report = reports[net_id]
        geometry_length = wire_length + extension_adjustment

        if len(electrical_groups) != 1:
            errors.append(
                f"{logical}: route plus foundry pins has {len(electrical_groups)} groups"
            )
        if cycle_rank != 0:
            errors.append(f"{logical}: route graph has cycle rank {cycle_rank}")
        if missed_pins:
            errors.append(f"{logical}: route misses foundry pins {missed_pins}")
        if unattached_leaves:
            errors.append(f"{logical}: {len(unattached_leaves)} dead route leaves")
        if unexpected_layers:
            errors.append(f"{logical}: unexpected route layers {unexpected_layers}")
        if unexpected_wire_layers:
            errors.append(
                f"{logical}: unexpected wire layers {unexpected_wire_layers}"
            )
        if int(report["pin_count"]) != pin_count:
            errors.append(f"{logical}: wire-report pin count differs")
        if int(report["via_count"]) != len(vias):
            errors.append(f"{logical}: wire-report via count differs")
        if abs(float(report["wire_length_um"]) - geometry_length) > 0.011:
            errors.append(
                f"{logical}: DEF length {geometry_length:.3f} um differs from "
                f"OpenROAD {float(report['wire_length_um']):.3f} um"
            )

        layer_net_counts.update(layers)
        total_wire += wire_length
        total_vias += len(vias)
        audited.append({
            "net": logical,
            "net_id": net_id,
            "pin_count": pin_count,
            "wire_length_um": round(wire_length, 6),
            "reported_geometry_length_um": round(geometry_length, 6),
            "via_count": len(vias),
            "layers": sorted(layers, key=LAYER_ORDER.__getitem__),
            "route_group_count": len(route_groups),
            "electrical_group_count": len(electrical_groups),
            "cycle_rank": cycle_rank,
            "leaf_count": len(leaves),
            "dead_leaf_count": len(unattached_leaves),
            "missed_pin_count": len(missed_pins),
        })

    if len(audited) != int(summary["net_count"]):
        errors.append("audited route count differs from the generated input manifest")
    maximum_degree = max(
        (len(endpoints) for endpoints in mapping["nets"].values()), default=0
    )
    if maximum_degree > 17:
        errors.append(f"logical maximum endpoint count {maximum_degree} exceeds 17")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "shared V3 controller internal signal routes; power and external handoffs excluded",
        "route_count": len(audited),
        "expected_route_count": int(summary["net_count"]),
        "logical_maximum_endpoint_count": maximum_degree,
        "total_centerline_wire_length_um": round(total_wire, 6),
        "total_via_count": total_vias,
        "nets_using_layer": dict(
            sorted(layer_net_counts.items(), key=lambda item: LAYER_ORDER[item[0]])
        ),
        "maximum_route_layer": max(
            layer_net_counts, key=LAYER_ORDER.__getitem__, default=None
        ),
        "final_openroad_layer_length_um": final_layer_lengths,
        "final_openroad_violation_count": violation_counts[-1] if violation_counts else None,
        "inaccessible_standard_cell_pin_count": pin_access[-1] if pin_access else None,
        "source_sha256": {
            "input_summary": file_sha256(summary_path),
            "placement": file_sha256(placement_path),
            "mapping": file_sha256(mapping_path),
            "generator": file_sha256(generator_path),
            "frozen_source_gds": file_sha256(frozen_source_gds),
        },
        "artifact_sha256": {
            "routed_def": file_sha256(routed_def_path),
            "detailed_route_drc": file_sha256(drc_path),
            "openroad_log": file_sha256(log_path),
            "wire_length": file_sha256(wire_path),
            "guide_coverage": file_sha256(guide_path),
        },
        "nets": audited,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal",
    )
    parser.add_argument(
        "--placement", type=Path,
        default=ROOT / "build/v3/control_placement/physical_control_placement.json",
    )
    parser.add_argument(
        "--mapping", type=Path,
        default=ROOT / "build/v3/control_mapping/physical_mapping.json",
    )
    parser.add_argument(
        "--generator", type=Path,
        default=ROOT / "v3/tools/generate_physical_control_openroad_inputs.py",
    )
    parser.add_argument(
        "--frozen-source-gds", type=Path,
        default=ROOT / "v3/frozen/four_channel_power_integration/v3_four_channel_power_integration.gds",
    )
    parser.add_argument(
        "--power-plan", type=Path,
        default=ROOT / "v3/layout/physical_control_power_plan.json",
    )
    parser.add_argument(
        "--report", type=Path,
        default=ROOT / "build/v3/control_routing/openroad_internal/route_audit.json",
    )
    args = parser.parse_args()
    report = validate(
        args.workdir,
        args.placement,
        args.mapping,
        args.generator,
        args.frozen_source_gds,
        args.power_plan,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in (
        "status", "errors", "route_count", "logical_maximum_endpoint_count",
        "total_centerline_wire_length_um", "total_via_count",
        "nets_using_layer", "maximum_route_layer",
    )}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
