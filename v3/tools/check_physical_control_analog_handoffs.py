#!/usr/bin/env python3
"""Independently audit the V3 controller-to-analog detailed routes.

The router's empty DRC report proves geometric legality only.  This checker
reconstructs every DEF route as a conductor graph, attaches the declared
top-level pin rectangles, and proves endpoint coverage, connectivity, and the
absence of floating leaves or routing loops.  It also freezes exact source and
artifact hashes so a later regeneration cannot silently replace the candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))
from check_control_openroad_routes import (  # noqa: E402
    LAYER_ORDER,
    TOP_PIN_CONNECTION_RE,
    components,
    net_blocks,
    parse_route,
    route_graph,
    wire_report,
)


DBU = 1000.0
ALLOWED_CONDUCTOR_LAYERS = {"met2", "met3", "met4"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attach_top_pins(
    graph: dict[tuple[str, int, int], set[tuple[str, int, int]]],
    pin_names: list[str],
    pins: dict[str, dict[str, Any]],
    coordinate_offset_um: list[float],
) -> tuple[
    dict[tuple[str, int, int], set[tuple[str, int, int]]],
    dict[str, set[tuple[str, int, int]]],
]:
    """Attach route nodes only through their declared DEF pin conductors."""

    result: dict[tuple[str, int, int], set[tuple[str, int, int]]] = defaultdict(set)
    for node, neighbours in graph.items():
        result[node].update(neighbours)
    ox, oy = map(float, coordinate_offset_um)
    memberships: dict[str, set[tuple[str, int, int]]] = {}
    for pin_name in pin_names:
        pin = pins[pin_name]
        x0, y0, x1, y1 = map(float, pin["rect_um"])
        rectangle = (
            pin["layer"],
            round((x0 - ox) * DBU),
            round((y0 - oy) * DBU),
            round((x1 - ox) * DBU),
            round((y1 - oy) * DBU),
        )
        found = {
            node
            for node in graph
            if node[0] == rectangle[0]
            and rectangle[1] - 1 <= node[1] <= rectangle[3] + 1
            and rectangle[2] - 1 <= node[2] <= rectangle[4] + 1
        }
        memberships[pin_name] = found
        pin_node = (f"PIN:{pin_name}", 0, 0)
        result.setdefault(pin_node, set())
        for node in found:
            result[pin_node].add(node)
            result[node].add(pin_node)
    return result, memberships


def validate(workdir: Path, plan_path: Path, generator_path: Path) -> dict[str, Any]:
    paths = {
        "input_def": workdir / "input.def",
        "input_summary": workdir / "input_summary.json",
        "routed_def": workdir / "routed.def",
        "detailed_route_drc": workdir / "detailed_route_drc.rpt",
        "openroad_log": workdir / "openroad.log",
        "wire_length": workdir / "wire_length.csv",
        "guide_coverage": workdir / "guide_coverage.csv",
        "route_guide": workdir / "route.guide",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError(f"missing handoff-route artifacts: {missing}")

    summary = json.loads(paths["input_summary"].read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    provenance = summary.get("provenance", {})
    expected_provenance = {
        "plan_sha256": sha256(plan_path),
        "source_gds_sha256": sha256(ROOT / plan["source_checkpoint"]["gds"]),
        "generator_sha256": sha256(generator_path),
    }
    for key, expected in expected_provenance.items():
        if provenance.get(key) != expected:
            errors.append(f"input provenance {key} differs from the current source")
    if provenance.get("source_gds_sha256") != plan["source_checkpoint"]["sha256"]:
        errors.append("input source GDS is not the frozen plan checkpoint")
    if int(summary.get("net_count", -1)) != int(plan["expected_net_count"]):
        errors.append("input net count differs from the handoff plan")
    if int(summary.get("pin_count", -1)) != int(plan["expected_pin_count"]):
        errors.append("input pin count differs from the handoff plan")
    if summary.get("policy") != plan.get("policy"):
        errors.append("input routing policy differs from the handoff plan")
    if paths["detailed_route_drc"].read_bytes():
        errors.append("detailed-route DRC report is not empty")

    log_text = paths["openroad_log"].read_text(encoding="utf-8")
    violation_counts = [
        int(value) for value in re.findall(r"Number of violations = (\d+)", log_text)
    ]
    if not violation_counts or violation_counts[-1] != 0:
        errors.append("final detailed-route violation count is not zero")
    routed_counts = [
        int(value) for value in re.findall(r"Routed nets:\s*(\d+)", log_text)
    ]
    if not routed_counts or routed_counts[-1] != int(plan["expected_net_count"]):
        errors.append("global route did not route every expected handoff net")
    pin_access = [
        int(value) for value in re.findall(r"#stdCellPinNoAp\s*=\s*(\d+)", log_text)
    ]
    if not pin_access or pin_access[-1] != 0:
        errors.append("OpenROAD reports inaccessible handoff pins")
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
    if final_layer_lengths.get("met5", 0) != 0:
        errors.append("production handoff route uses forbidden M5")
    if final_layer_lengths.get("li1", 0) != 0 or final_layer_lengths.get("met1", 0) != 0:
        errors.append("production handoff route escaped below M2")

    blocks = net_blocks(paths["routed_def"].read_text(encoding="utf-8"))
    reports = wire_report(paths["wire_length"])
    expected_ids = set(summary["net_ids"])
    if set(blocks) != expected_ids:
        errors.append("routed DEF net IDs differ from the generated manifest")
    if set(reports) != expected_ids:
        errors.append("wire report net IDs differ from the generated manifest")

    pin_to_net: dict[str, str] = {}
    for net_index, net in enumerate(summary["nets"]):
        net_id = f"N{net_index:03d}"
        for endpoint_index in range(1 + len(net["targets"])):
            pin_to_net[f"P{net_index:03d}_{endpoint_index}"] = net_id
    if set(pin_to_net) != set(summary["pins"]):
        errors.append("pin manifest cannot be reconstructed from the logical nets")

    audited: list[dict[str, Any]] = []
    class_totals: Counter[str] = Counter()
    layer_net_counts: Counter[str] = Counter()
    total_wire = 0.0
    total_vias = 0
    for net_id in sorted(expected_ids):
        if net_id not in blocks or net_id not in reports:
            continue
        net_index = int(net_id[1:])
        logical_spec = summary["nets"][net_index]
        logical = summary["net_ids"][net_id]
        block = blocks[net_id]
        connection_text = block.split("+ USE", 1)[0]
        pin_names = TOP_PIN_CONNECTION_RE.findall(connection_text)
        expected_pins = sorted(pin for pin, owner in pin_to_net.items() if owner == net_id)
        if sorted(pin_names) != expected_pins:
            errors.append(f"{logical}: DEF pin set differs from the endpoint contract")
        try:
            segments, vias, layers, extension_adjustment = parse_route(block)
            graph, wire_length = route_graph(segments, vias)
            electrical_graph, memberships = attach_top_pins(
                graph,
                pin_names,
                summary["pins"],
                summary["coordinate_offset_um"],
            )
        except (KeyError, ValueError) as error:
            errors.append(f"{logical}: {error}")
            continue

        route_groups = components(graph)
        electrical_groups = components(electrical_graph)
        leaves = [node for node, neighbours in graph.items() if len(neighbours) == 1]
        attached = set().union(*memberships.values()) if memberships else set()
        dead_leaves = [node for node in leaves if node not in attached]
        edge_count = sum(len(neighbours) for neighbours in graph.values()) // 2
        cycle_rank = edge_count - len(graph) + len(route_groups)
        missed_pins = sorted(name for name, nodes in memberships.items() if not nodes)
        unexpected_layers = sorted(layers - ALLOWED_CONDUCTOR_LAYERS)
        report = reports[net_id]
        geometry_length = wire_length + extension_adjustment
        xs = [float(endpoint["rect_um"][0]) for endpoint in [logical_spec["source"], *logical_spec["targets"]]]
        ys = [float(endpoint["rect_um"][1]) for endpoint in [logical_spec["source"], *logical_spec["targets"]]]
        hpwl = max(xs) - min(xs) + max(ys) - min(ys)
        detour_ratio = wire_length / max(hpwl, 0.001)

        if len(electrical_groups) != 1:
            errors.append(f"{logical}: route plus pins has {len(electrical_groups)} groups")
        if cycle_rank != 0:
            errors.append(f"{logical}: route graph has cycle rank {cycle_rank}")
        if missed_pins:
            errors.append(f"{logical}: route misses declared pins {missed_pins}")
        if dead_leaves:
            errors.append(f"{logical}: {len(dead_leaves)} floating route leaves")
        if unexpected_layers:
            errors.append(f"{logical}: unexpected route layers {unexpected_layers}")
        if int(report["pin_count"]) != len(pin_names):
            errors.append(f"{logical}: wire-report pin count differs")
        if int(report["via_count"]) != len(vias):
            errors.append(f"{logical}: wire-report via count differs")
        if abs(float(report["wire_length_um"]) - geometry_length) > 0.011:
            errors.append(
                f"{logical}: DEF length {geometry_length:.3f} um differs from "
                f"OpenROAD {float(report['wire_length_um']):.3f} um"
            )
        # These are compact top-level crossings through a dense frozen macro.
        # Reject pathological routing, but retain the measured value in the
        # evidence so a tighter threshold can be adopted after visual review.
        if detour_ratio > 4.0:
            errors.append(f"{logical}: detour ratio {detour_ratio:.3f} exceeds 4.0")

        class_totals[logical_spec["route_class"]] += 1
        layer_net_counts.update(layers)
        total_wire += wire_length
        total_vias += len(vias)
        audited.append({
            "net": logical,
            "net_id": net_id,
            "route_class": logical_spec["route_class"],
            "pin_count": len(pin_names),
            "wire_length_um": round(wire_length, 6),
            "reported_geometry_length_um": round(geometry_length, 6),
            "hpwl_um": round(hpwl, 6),
            "detour_ratio": round(detour_ratio, 6),
            "via_count": len(vias),
            "layers": sorted(layers, key=LAYER_ORDER.__getitem__),
            "route_group_count": len(route_groups),
            "electrical_group_count": len(electrical_groups),
            "cycle_rank": cycle_rank,
            "leaf_count": len(leaves),
            "dead_leaf_count": len(dead_leaves),
            "missed_pin_count": len(missed_pins),
        })

    if len(audited) != int(plan["expected_net_count"]):
        errors.append("audited route count differs from the handoff plan")
    if dict(class_totals) != plan["route_classes"]:
        errors.append("audited route-class counts differ from the handoff plan")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "scope": "41 V3 controller-to-analog and phase-tree physical handoffs",
        "route_count": len(audited),
        "pin_count": sum(item["pin_count"] for item in audited),
        "route_class_counts": dict(sorted(class_totals.items())),
        "total_centerline_wire_length_um": round(total_wire, 6),
        "total_via_count": total_vias,
        "nets_using_layer": dict(
            sorted(layer_net_counts.items(), key=lambda item: LAYER_ORDER[item[0]])
        ),
        "maximum_route_layer": max(
            layer_net_counts, key=LAYER_ORDER.__getitem__, default=None
        ),
        "maximum_detour": max(audited, key=lambda item: item["detour_ratio"], default=None),
        "maximum_via_count": max(audited, key=lambda item: item["via_count"], default=None),
        "final_openroad_layer_length_um": final_layer_lengths,
        "final_openroad_violation_count": violation_counts[-1] if violation_counts else None,
        "source_sha256": {
            "plan": sha256(plan_path),
            "generator": sha256(generator_path),
            "input_summary": sha256(paths["input_summary"]),
            "source_gds": sha256(ROOT / plan["source_checkpoint"]["gds"]),
        },
        "artifact_sha256": {name: sha256(path) for name, path in paths.items()},
        "nets": audited,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/openroad",
    )
    parser.add_argument(
        "--plan", type=Path,
        default=ROOT / "v3/layout/physical_control_analog_handoff_plan.json",
    )
    parser.add_argument(
        "--generator", type=Path,
        default=ROOT / "v3/tools/generate_physical_control_analog_handoff_inputs.py",
    )
    parser.add_argument(
        "--report", type=Path,
        default=ROOT / "build/v3/control_analog_handoffs/openroad/route_audit.json",
    )
    args = parser.parse_args()
    report = validate(args.workdir, args.plan, args.generator)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in (
        "status", "errors", "route_count", "pin_count", "route_class_counts",
        "total_centerline_wire_length_um", "total_via_count",
        "nets_using_layer", "maximum_route_layer", "maximum_detour",
        "maximum_via_count",
    )}, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
