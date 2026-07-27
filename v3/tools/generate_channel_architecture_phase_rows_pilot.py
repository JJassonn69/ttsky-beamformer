#!/usr/bin/env python3
"""Add exact per-row G1/G2/G4/G8 phase collectors to the service skeleton."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import generate_channel_architecture_service_pilot as service_gen
import generate_channel_row_pilot as row_gen


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "build/v3/channel_architecture_feasibility/channel_matrix_placement.json"
ARCHITECTURE = ROOT / "v3/layout/channel_routing_architecture.json"
UNIT = ROOT / "v3/layout/vector_unit_placement.json"
CATALOG = ROOT / "v3/layout/channel_pcell_catalog.json"
BUILD = ROOT / "build/v3/channel_architecture_phase_rows"
DEFAULT_OUTPUT = BUILD / "build.tcl"
DEFAULT_ROOTS = BUILD / "phase_row_roots.json"
TOP = "v3_channel_architecture_phase_rows"
ROOT_STEM_UM = 0.40


def branch_x_by_net(selected: dict[str, Any]) -> dict[str, float]:
    side = [float(value) for value in selected["phase_distribution"]["side_bank_trunks_x_um"]]
    internal = [float(value) for value in selected["phase_distribution"]["internal_g1_trunks_x_um"]]
    if len(side) != 6 or len(internal) != 2:
        raise RuntimeError("selected phase handoff allocation changed")
    return {
        "g1_lon": internal[0], "g1_lop": internal[1],
        "g2_lon": side[0], "g2_lop": side[1],
        "g4_lon": side[2], "g4_lop": side[3],
        "g8_lon": side[4], "g8_lop": side[5],
    }


def branch_x_for_row(
    selected: dict[str, Any], fixed: dict[str, float], row: int,
    group: int, polarity: str, *, mixed_row: bool, centre_group: int,
) -> float:
    if mixed_row and group == centre_group == 8:
        values = [
            float(value)
            for value in selected["phase_distribution"]["mixed_centre_g8_handoffs_x_um"]
        ]
        if len(values) != 2:
            raise RuntimeError("mixed-centre G8 handoff allocation changed")
        return values[0 if polarity == "lon" else 1]
    return fixed[f"g{group}_{polarity}"]


def local_lop_covers_x(instance: dict[str, Any], x_value: float) -> bool:
    route = instance["local_lo_routes"]["lop"]
    root_y = float(route["root"][1])
    return any(
        item["layer"] == "metal4"
        and float(item["from"][1]) == float(item["to"][1]) == root_y
        and min(float(item["from"][0]), float(item["to"][0])) - 0.20 <= x_value
        <= max(float(item["from"][0]), float(item["to"][0])) + 0.20
        for item in route["segments"]
    )


def phase_geometry(
    matrix: dict[str, Any], architecture: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    selected_name = architecture["decision"]["selected"]
    selected = architecture["candidates"][selected_name]
    tracks_by_row = {
        int(item["row_top_to_bottom"]): item for item in selected["row_track_plan"]
    }
    branches = branch_x_by_net(selected)
    by_row: dict[int, list[dict[str, Any]]] = {}
    for item in matrix["matrix"]["instances"]:
        by_row.setdefault(int(item["row_top_to_bottom"]), []).append(item)
    commands: list[str] = []
    labels: list[str] = []
    roots: list[dict[str, Any]] = []

    for row, instances in sorted(by_row.items()):
        instances.sort(key=lambda item: item["column_left_to_right"])
        track_record = tracks_by_row[row]
        by_group: dict[int, list[dict[str, Any]]] = {}
        for instance in instances:
            by_group.setdefault(int(instance["group_weight"]), []).append(instance)
        centre_group = int(track_record["centre_group"])
        outer_group = track_record["outer_group"]
        expected = {centre_group} | ({int(outer_group)} if outer_group is not None else set())
        if set(by_group) != expected:
            raise RuntimeError(f"row {row} group allocation changed: {sorted(by_group)}")

        for group, members in sorted(by_group.items()):
            family = "centre" if group == centre_group else "outer"
            for polarity in ("lon", "lop"):
                net = f"g{group}_{polarity}"
                track_y = float(track_record["tracks"][f"phase_{family}_{polarity}_m3"])
                branch_x = branch_x_for_row(
                    selected, branches, row, group, polarity,
                    mixed_row=outer_group is not None, centre_group=centre_group,
                )
                local_roots = sorted(
                    ([float(value) for value in item["local_lo_routes"][polarity]["root"]] for item in members),
                    key=lambda point: point[0],
                )
                direct_lop = (
                    polarity == "lop" and len(members) == 1
                    and local_lop_covers_x(members[0], branch_x)
                    and abs(local_roots[0][1] - track_y) < 1e-9
                )
                if not direct_lop:
                    for local_root in local_roots:
                        if polarity == "lon":
                            if abs(local_root[1] - track_y) > 1e-9:
                                commands.append(service_gen.wire_v(
                                    "metal3", local_root[0], local_root[1], track_y, 0.40,
                                ))
                        else:
                            if abs(local_root[1] - track_y) > 1e-9:
                                commands.append(service_gen.wire_v(
                                    "metal4", local_root[0], local_root[1], track_y, 0.40,
                                ))
                            commands.extend(service_gen.via3([local_root[0], track_y]))
                    left = min(branch_x, local_roots[0][0])
                    right = max(branch_x, local_roots[-1][0])
                    commands.append(service_gen.wire_h(
                        "metal3", left - 0.20, right + 0.20, track_y, 0.40,
                    ))
                    commands.extend(service_gen.via3([branch_x, track_y]))
                    if polarity == "lop":
                        nearest = min(local_roots, key=lambda point: abs(point[0] - branch_x))
                        centre_gap = abs(nearest[0] - branch_x) - 0.40
                        if 0.0 < centre_gap < 0.30:
                            commands.append(service_gen.wire_h(
                                "metal4", nearest[0], branch_x, track_y, 0.40,
                            ))
                # Point LON stems downward and LOP stems upward.  A 0.40 um
                # extension plus the 0.40 um Via-3 landing gives exactly the
                # 0.24 um2 M4 area while keeping the next phase track clear.
                root_y = round(
                    track_y + (ROOT_STEM_UM if polarity == "lop" else -ROOT_STEM_UM),
                    6,
                )
                commands.append(service_gen.wire_v(
                    "metal4", branch_x, track_y, root_y, 0.40,
                ))
                label_name = f"{net}_r{row}"
                labels.append(row_gen.label(label_name, [branch_x, root_y], "metal4"))
                roots.append({
                    "net": net, "row_top_to_bottom": row,
                    "point": [branch_x, root_y], "layer": "metal4",
                    "track_y_um": track_y, "member_units": [item["name"] for item in members],
                    "direct_m4_lop_handoff": direct_lop,
                })
    manifest = {
        "schema_version": 1,
        "units": "um",
        "status": "exact per-row phase handoff candidate; global inter-row trees absent",
        "selected_architecture": selected_name,
        "roots": roots,
        "constraints": {
            "root_stem_um": ROOT_STEM_UM,
            "floating_stubs_allowed": False,
            "orphan_vias_allowed": False,
            "global_tree_geometry_present": False,
        },
        "provenance": {"generator": "v3/tools/generate_channel_architecture_phase_rows_pilot.py"},
    }
    return commands, labels, manifest


def build_tcl(
    matrix: dict[str, Any], architecture: dict[str, Any], unit: dict[str, Any],
    catalog: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    source = service_gen.build_tcl(matrix, architecture, unit, catalog)
    source = source.replace("channel_architecture_service", "channel_architecture_phase_rows")
    source = source.replace("v3_channel_architecture_service", TOP)
    source = source.replace("V3_CHANNEL_ARCHITECTURE_SERVICE", "V3_CHANNEL_ARCHITECTURE_PHASE_ROWS")
    source = source.replace("channel-architecture service pilot", "channel-architecture phase-row pilot")
    local_alias = re.compile(
        r"box [^\n]+\n"
        r"label u\d{2}_(?:lop|lon) center metal[34]\n"
        r"port make\nport class input\nport use signal\n"
        r"port connections n s e w\n?"
    )
    source, removed = local_alias.subn("", source)
    if removed != 30:
        raise RuntimeError(f"expected to remove 30 unit-local phase aliases, removed {removed}")
    commands, labels, manifest = phase_geometry(matrix, architecture)
    insertion = "\n".join(commands + labels)
    marker = "\nsave $TOP.mag\nwriteall force\n"
    if source.count(marker) != 1:
        raise RuntimeError("phase-row insertion marker changed")
    return source.replace(marker, f"\n{insertion}{marker}"), manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--architecture", type=Path, default=ARCHITECTURE)
    parser.add_argument("--unit", type=Path, default=UNIT)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--roots-output", type=Path, default=DEFAULT_ROOTS)
    args = parser.parse_args()
    values = [json.loads(path.read_text(encoding="utf-8")) for path in (
        args.matrix, args.architecture, args.unit, args.catalog,
    )]
    source, manifest = build_tcl(*values)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8")
    args.roots_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    print(args.roots_output)


if __name__ == "__main__":
    main()
