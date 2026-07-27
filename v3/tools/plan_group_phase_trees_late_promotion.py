#!/usr/bin/env python3
"""Route the eight V3 phase trees against the exact late-promotion service GDS.

This planner deliberately treats the already validated 15-cell/service layout
as immutable.  It adds short same-layer escapes at the thirty local LO roots,
then joins those escapes to eight top ports with a bend/via-aware detailed
router.  Existing M3/M4 shapes and previously accepted phase trees are hard
obstacles, so a visually straight route may never silently cross another net.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.check_gds_flat_rules import MET3, MET4, flatten_rectangles, parse_gds  # noqa: E402


MATRIX = ROOT / "v3/layout/channel_matrix_late_promotion.json"
DEFAULT_GDS = ROOT / "build/v3/channel_architecture_service_late_promotion/v3_channel_architecture_service_late_promotion.gds"
DEFAULT_OUTPUT = ROOT / "v3/layout/group_phase_trees_late_promotion.json"
TOP = "v3_channel_architecture_service_late_promotion"
GDS_ORIGIN = (20.0, 20.0)

# Every local root and row pitch lands exactly on this grid.  The 40 nm grid is
# fine enough to preserve the approved geometry while avoiding a 10 nm search.
STEP = 0.04
X_OFFSET = 0.02
Y_OFFSET = 0.03
X_MIN = 0.02
X_MAX = 19.30
Y_MIN = 20.03
Y_MAX = 111.23
ROUTE_WIDTH = 0.40
SPACING = 0.30
ESCAPE_UM = 0.72
# The global tree uses a symmetric 0.50 x 0.50 um Via-3 landing.  This meets
# both 0.24 um2 metal-area rules and needs only 0.05 um more clearance per
# side than a 0.40 um route (unlike the legacy asymmetric 0.62 um M3 plate).
VIA_LANDING_EXTRA = 0.00

# Eight orderly top ports at 0.72 um pitch.  They sit above the service rows
# and can later land directly in the selector band without a second fan-out.
ROOTS = {
    "g1_lon": [7.22, 110.83],
    "g1_lop": [7.94, 110.83],
    "g2_lon": [8.66, 110.83],
    "g2_lop": [9.38, 110.83],
    "g4_lon": [10.10, 110.83],
    "g4_lop": [10.82, 110.83],
    "g8_lon": [11.54, 110.83],
    "g8_lop": [12.26, 110.83],
}

GridPoint = tuple[int, int, int]
State = tuple[int, int, int, int]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ix(value: float) -> int:
    return int(round((value - X_OFFSET) / STEP))


def iy(value: float) -> int:
    return int(round((value - Y_OFFSET) / STEP))


def xy(point: GridPoint) -> list[float]:
    return [
        round(X_OFFSET + point[0] * STEP, 6),
        round(Y_OFFSET + point[1] * STEP, 6),
    ]


IX_MIN, IX_MAX = ix(X_MIN), ix(X_MAX)
IY_MIN, IY_MAX = iy(Y_MIN), iy(Y_MAX)


def point(value: list[float], layer: int) -> GridPoint:
    result = (ix(value[0]), iy(value[1]), layer)
    snapped = xy(result)
    if abs(snapped[0] - value[0]) > 1e-6 or abs(snapped[1] - value[1]) > 1e-6:
        raise ValueError(f"point {value} is off the {STEP:.2f} um route grid; snaps to {snapped}")
    return result


def add_rect(blocked: set[tuple[int, int]], rect: tuple[float, float, float, float], margin: float) -> None:
    x0, y0, x1, y1 = rect
    lo_x = max(IX_MIN, math.ceil((x0 - margin - X_OFFSET) / STEP - 1e-9))
    hi_x = min(IX_MAX, math.floor((x1 + margin - X_OFFSET) / STEP + 1e-9))
    lo_y = max(IY_MIN, math.ceil((y0 - margin - Y_OFFSET) / STEP - 1e-9))
    hi_y = min(IY_MAX, math.floor((y1 + margin - Y_OFFSET) / STEP + 1e-9))
    for gx in range(lo_x, hi_x + 1):
        for gy in range(lo_y, hi_y + 1):
            blocked.add((gx, gy))


def base_obstacles(
    gds: Path,
) -> tuple[dict[int, set[tuple[int, int]]], dict[int, set[tuple[int, int]]]]:
    structures, database_um = parse_gds(gds)
    rectangles = flatten_rectangles(structures, TOP, database_um)
    output = {0: set(), 1: set()}
    via_output = {0: set(), 1: set()}
    for layer_index, layer in enumerate((MET3, MET4)):
        for raw in rectangles[layer]:
            rect = (
                raw[0] - GDS_ORIGIN[0], raw[1] - GDS_ORIGIN[1],
                raw[2] - GDS_ORIGIN[0], raw[3] - GDS_ORIGIN[1],
            )
            route_margin = ROUTE_WIDTH / 2.0 + SPACING
            add_rect(output[layer_index], rect, route_margin)
            via_margin = route_margin + VIA_LANDING_EXTRA
            add_rect(via_output[layer_index], rect, via_margin)
    return output, via_output


def grid_line(first: GridPoint, second: GridPoint) -> list[GridPoint]:
    if first[2] != second[2]:
        raise ValueError("a fixed line cannot change layer")
    if first[0] != second[0] and first[1] != second[1]:
        raise ValueError(f"non-Manhattan fixed line: {first} -> {second}")
    dx = 0 if first[0] == second[0] else (1 if second[0] > first[0] else -1)
    dy = 0 if first[1] == second[1] else (1 if second[1] > first[1] else -1)
    count = max(abs(second[0] - first[0]), abs(second[1] - first[1]))
    return [(first[0] + index * dx, first[1] + index * dy, first[2]) for index in range(count + 1)]


def reserve_path(
    reservations: dict[GridPoint, set[str]], name: str,
    path: Iterable[GridPoint], clearance: float,
) -> None:
    radius = int(math.floor((clearance - 1e-9) / STEP))
    for gx, gy, layer in path:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) * STEP < clearance - 1e-9 and abs(dy) * STEP < clearance - 1e-9:
                    reservations.setdefault((gx + dx, gy + dy, layer), set()).add(name)


def mark_path(
    blocked: dict[int, set[tuple[int, int]]],
    via_blocked: dict[int, set[tuple[int, int]]],
    path: Iterable[GridPoint],
) -> None:
    base_clearance = ROUTE_WIDTH + SPACING
    for gx, gy, layer in path:
        clearance = base_clearance
        radius = int(math.floor((clearance - 1e-9) / STEP))
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) * STEP < clearance - 1e-9 and abs(dy) * STEP < clearance - 1e-9:
                    blocked[layer].add((gx + dx, gy + dy))
        via_clearance = base_clearance + VIA_LANDING_EXTRA
        via_radius = int(math.floor((via_clearance - 1e-9) / STEP))
        for dx in range(-via_radius, via_radius + 1):
            for dy in range(-via_radius, via_radius + 1):
                if abs(dx) * STEP < via_clearance - 1e-9 and abs(dy) * STEP < via_clearance - 1e-9:
                    via_blocked[layer].add((gx + dx, gy + dy))


def heuristic(state: State, goal: GridPoint) -> int:
    gx, gy, layer, _direction = state
    return abs(gx - goal[0]) + abs(gy - goal[1]) + (12 if layer != goal[2] else 0)


def route_to_tree(
    start: GridPoint, tree: set[GridPoint], blocked: dict[int, set[tuple[int, int]]],
    via_blocked: dict[int, set[tuple[int, int]]], name: str,
    reservations: dict[GridPoint, set[str]],
) -> list[GridPoint]:
    """Join start to the nearest useful point in tree with strong bend/via penalties."""
    seeds = {
        item for item in tree
        if any((item[0] + dx, item[1] + dy, item[2]) not in tree for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    }
    queue: list[tuple[int, int, State]] = []
    costs: dict[State, int] = {}
    prior: dict[State, State | None] = {}
    serial = 0
    for seed in seeds:
        initial: State = (*seed, 4)
        costs[initial] = 0
        prior[initial] = None
        heapq.heappush(queue, (heuristic(initial, start), serial, initial))
        serial += 1
    final: State | None = None
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    while queue:
        _priority, _serial, current = heapq.heappop(queue)
        cost = costs[current]
        gx, gy, layer, old_direction = current
        if (gx, gy, layer) == start:
            final = current
            break
        for direction, (dx, dy) in enumerate(directions):
            nx, ny = gx + dx, gy + dy
            if not (IX_MIN <= nx <= IX_MAX and IY_MIN <= ny <= IY_MAX):
                continue
            owners = reservations.get((nx, ny, layer), set())
            if owners - {name}:
                continue
            own_access = bool(owners) and owners <= {name}
            if (nx, ny) in blocked[layer] and not own_access and (nx, ny, layer) not in tree:
                continue
            bend_cost = 0 if old_direction in (4, direction) else 80
            state = (nx, ny, layer, direction)
            candidate = cost + 10 + bend_cost
            if candidate < costs.get(state, 1 << 60):
                costs[state] = candidate
                prior[state] = current
                heapq.heappush(queue, (candidate + 10 * heuristic(state, start), serial, state))
                serial += 1
        other = 1 - layer
        other_owners = reservations.get((gx, gy, other), set())
        here_owners = reservations.get((gx, gy, layer), set())
        if (
            not (other_owners - {name}) and not (here_owners - {name})
            and ((gx, gy) not in via_blocked[other] or (other_owners and other_owners <= {name}) or (gx, gy, other) in tree)
            and ((gx, gy) not in via_blocked[layer] or (here_owners and here_owners <= {name}) or (gx, gy, layer) in tree)
        ):
            state = (gx, gy, other, 4)
            candidate = cost + 600
            if candidate < costs.get(state, 1 << 60):
                costs[state] = candidate
                prior[state] = current
                heapq.heappush(queue, (candidate + 10 * heuristic(state, start), serial, state))
                serial += 1
    if final is None:
        raise RuntimeError(f"no route for {name} from {xy(start)}")
    path: list[GridPoint] = []
    cursor: State | None = final
    while cursor is not None:
        path.append((cursor[0], cursor[1], cursor[2]))
        cursor = prior[cursor]
    return path


def compress(path: list[GridPoint]) -> tuple[list[dict[str, Any]], list[list[float]]]:
    segments: list[dict[str, Any]] = []
    vias: list[list[float]] = []
    start = path[0]
    previous = path[0]
    previous_direction: tuple[int, int, int] | None = None
    for current in path[1:]:
        if current[2] != previous[2]:
            if start != previous:
                segments.append({
                    "from": xy(start), "to": xy(previous),
                    "layer": "metal3" if previous[2] == 0 else "metal4",
                    "width_um": ROUTE_WIDTH,
                })
            vias.append(xy(current))
            start = current
            previous = current
            previous_direction = None
            continue
        direction = (current[0] - previous[0], current[1] - previous[1], current[2])
        if previous_direction is not None and direction != previous_direction:
            segments.append({
                "from": xy(start), "to": xy(previous),
                "layer": "metal3" if previous[2] == 0 else "metal4",
                "width_um": ROUTE_WIDTH,
            })
            start = previous
        previous_direction = direction
        previous = current
    if start != previous:
        segments.append({
            "from": xy(start), "to": xy(previous),
            "layer": "metal3" if previous[2] == 0 else "metal4",
            "width_um": ROUTE_WIDTH,
        })
    return segments, vias


def terminals(matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in matrix["matrix"]["instances"]:
        group = int(instance["group_weight"])
        for polarity in ("lon", "lop"):
            route = instance["local_lo_routes"][polarity]
            local = [float(value) for value in route["root"]]
            escape = [local[0], round(local[1] + ESCAPE_UM, 6)]
            result[f"g{group}_{polarity}"].append({
                "unit": instance["name"], "local_root": local,
                "escape": escape, "layer": 0 if polarity == "lon" else 1,
            })
    for values in result.values():
        values.sort(key=lambda item: (item["escape"][1], item["escape"][0]))
    return dict(result)


def normalize_tree_geometry(trees: dict[str, Any]) -> None:
    """Apply exact, topology-preserving simplifications found by flat DRC.

    The A* search works on route centrelines.  These transformations account
    for real Via-3 landing width and remove two narrow same-net U slots while
    reducing, rather than adding, jogs.  Each change is regenerated from this
    source and must still pass extraction topology plus both physical decks.
    """
    via_retargets: dict[str, dict[tuple[float, float], tuple[float, float]]] = {
        "g2_lop": {(16.62, 68.91): (16.50, 68.91)},
        "g4_lop": {(14.54, 62.59): (14.66, 62.59)},
    }
    point_retargets: dict[str, dict[tuple[float, float], tuple[float, float]]] = {}
    for name in sorted(set(via_retargets) | set(point_retargets)):
        replacements = point_retargets.get(name, {})
        via_moves = via_retargets.get(name, {})
        tree = trees[name]
        for path in tree["paths"]:
            rewritten = []
            for segment in path["segments"]:
                item = dict(segment)
                layer_moves = {**replacements, **(via_moves if item["layer"] == "metal3" else {})}
                item["from"] = list(layer_moves.get(tuple(item["from"]), tuple(item["from"])))
                item["to"] = list(layer_moves.get(tuple(item["to"]), tuple(item["to"])))
                if item["from"] != item["to"]:
                    rewritten.append(item)
            path["segments"] = rewritten
            path["via3_points"] = [
                list(({**replacements, **via_moves}).get(tuple(via), tuple(via)))
                for via in path["via3_points"]
            ]
        tree["normalizations"] = [
            {"from": list(first), "to": list(second)}
            for first, second in sorted({**replacements, **via_moves}.items())
        ]
    # The two close same-net branch attachments otherwise form narrow U slots.
    # Filling the slot makes each attachment one solid T junction; it removes
    # metal rather than signal-path ambiguity and adds no floating geometry.
    trees["g8_lop"]["junction_fill_rectangles"] = [
        {"layer": "metal4", "bbox": [2.90, 102.15, 3.02, 102.47], "role": "solid_T_junction"},
    ]
    trees["g4_lop"]["junction_fill_rectangles"] = [
        {"layer": "metal4", "bbox": [16.82, 82.15, 16.94, 82.47], "role": "solid_T_junction"},
    ]

    # Give G1-LON and G8-LON dedicated 0.72 um-pitch M4 trunks.  G1 has one
    # leaf and moves to x=5.42; the eight-leaf G8 tree owns x=6.86.  This turns
    # the searched G8 layer ladder into one straight crossing trunk and cuts
    # its backbone Via-3 count from nine to three.
    g1_path = trees["g1_lon"]["paths"][0]
    if g1_path["terminal"]["unit"] != "U_R2_C1_G1":
        raise RuntimeError("G1-LON normalization ownership changed")
    g1_path["segments"] = [
        {"from": [9.66, 61.87], "to": [5.48, 61.87], "layer": "metal3", "width_um": 0.40},
        {"from": [5.48, 61.87], "to": [5.48, 110.83], "layer": "metal4", "width_um": 0.40},
        {"from": [5.48, 110.83], "to": [7.22, 110.83], "layer": "metal4", "width_um": 0.40},
    ]
    g1_path["via3_points"] = [[5.48, 61.87]]

    g8_paths = trees["g8_lon"]["paths"]
    expected_units = [
        "U_R4_C2_G8", "U_R4_C0_G8", "U_R4_C1_G8", "U_R3_C1_G8",
        "U_R1_C1_G8", "U_R0_C2_G8", "U_R0_C0_G8", "U_R0_C1_G8",
    ]
    if [item["terminal"]["unit"] for item in g8_paths] != expected_units:
        raise RuntimeError("G8-LON normalization ownership/order changed")
    g8_paths[0]["segments"] = [
        {"from": [16.62, 21.87], "to": [6.88, 21.87], "layer": "metal3", "width_um": 0.40},
        {"from": [6.88, 21.87], "to": [6.88, 106.79], "layer": "metal4", "width_um": 0.40},
        {"from": [6.88, 106.79], "to": [11.54, 106.79], "layer": "metal3", "width_um": 0.40},
        {"from": [11.54, 106.79], "to": [11.54, 110.83], "layer": "metal4", "width_um": 0.40},
    ]
    g8_paths[0]["via3_points"] = [[6.88, 21.87], [6.88, 106.79], [11.54, 106.79]]
    for segment in g8_paths[3]["segments"]:
        segment["from"] = [6.88 if value == 6.86 else value for value in segment["from"]]
        segment["to"] = [6.88 if value == 6.86 else value for value in segment["to"]]
    g8_paths[4]["segments"] = [
        {"from": [9.66, 81.87], "to": [6.88, 81.87], "layer": "metal3", "width_um": 0.40},
    ]
    g8_paths[4]["via3_points"] = [[6.88, 81.87]]
    g8_paths[6]["segments"] = [
        {"from": [2.70, 101.87], "to": [6.88, 101.87], "layer": "metal3", "width_um": 0.40},
    ]
    g8_paths[6]["via3_points"] = [[6.88, 101.87]]
    g8_paths[7]["segments"] = [
        {"from": [9.66, 101.87], "to": [6.88, 101.87], "layer": "metal3", "width_um": 0.40},
    ]
    g8_paths[7]["via3_points"] = []
    for path in trees["g4_lon"]["paths"]:
        for segment in path["segments"]:
            segment["from"] = [6.18 if value == 6.14 else value for value in segment["from"]]
            segment["to"] = [6.18 if value == 6.14 else value for value in segment["to"]]
        path["via3_points"] = [
            [6.18 if value == 6.14 else value for value in point]
            for point in path["via3_points"]
        ]
    trees["g1_lon"]["dedicated_trunk_normalization"] = {"m4_x_um": 5.48}
    trees["g4_lon"]["dedicated_trunk_normalization"] = {"m4_x_um": 6.18}
    trees["g8_lon"]["dedicated_trunk_normalization"] = {
        "m4_x_um": 6.88,
        "backbone_via3_count_before": 9,
        "backbone_via3_count_after": 3,
    }


def build(matrix_path: Path, gds: Path) -> dict[str, Any]:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    leaves_by_net = terminals(matrix)
    blocked, via_blocked = base_obstacles(gds)
    reservations: dict[GridPoint, set[str]] = {}
    fixed: dict[str, list[GridPoint]] = defaultdict(list)
    fixed_segments: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Protect every terminal before planning any net.  The reservation is on
    # its real layer only, so a via still must have a legal landing opposite it.
    access_clearance = ROUTE_WIDTH + SPACING
    for name, leaves in leaves_by_net.items():
        for leaf in leaves:
            path = grid_line(point(leaf["local_root"], leaf["layer"]), point(leaf["escape"], leaf["layer"]))
            fixed[name].extend(path)
            reserve_path(reservations, name, path, access_clearance)
            fixed_segments[name].append({
                "from": leaf["local_root"], "to": leaf["escape"],
                "layer": "metal3" if leaf["layer"] == 0 else "metal4",
                "width_um": ROUTE_WIDTH, "role": "local_root_escape",
            })
    for name, root_xy in ROOTS.items():
        root = point(root_xy, 1)
        fixed[name].append(root)
        reserve_path(reservations, name, [root], access_clearance)

    # Route high-fanout trees first.  Inside each tree, route the most distant
    # row first so later leaves naturally attach as branches instead of loops.
    order = ["g1_lon", "g1_lop", "g2_lon", "g2_lop", "g4_lon", "g4_lop", "g8_lon", "g8_lop"]
    trees: dict[str, Any] = {}
    for name in order:
        tree = {point(ROOTS[name], 1)}
        paths: list[dict[str, Any]] = []
        leaves = sorted(
            leaves_by_net[name],
            key=lambda item: (
                item["escape"][1],
                -abs(item["escape"][0] - 9.66),
                item["escape"][0],
            ),
        )
        for leaf in leaves:
            escape_path = grid_line(point(leaf["local_root"], leaf["layer"]), point(leaf["escape"], leaf["layer"]))
            routed = route_to_tree(
                point(leaf["escape"], leaf["layer"]), tree,
                blocked, via_blocked, name, reservations,
            )
            tree.update(escape_path)
            tree.update(routed)
            segments, vias = compress(routed)
            paths.append({
                "terminal": leaf, "role": "obstacle_aware_tree_branch",
                "segments": segments, "via3_points": vias,
            })
        mark_path(blocked, via_blocked, tree)
        lengths = []
        for path in paths:
            lengths.append(round(sum(
                abs(segment["to"][0] - segment["from"][0]) + abs(segment["to"][1] - segment["from"][1])
                for segment in path["segments"]
            ), 6))
        trees[name] = {
            "group": int(name[1]), "polarity": name.rsplit("_", 1)[1],
            "root": ROOTS[name], "root_layer": "metal4",
            "terminals": leaves_by_net[name], "paths": paths,
            "fixed_segments": fixed_segments[name],
            "grid_point_count": len(tree),
            "searched_branch_lengths_um": lengths,
        }
        print(f"planned {name}: {len(leaves)} leaves, {len(tree)} grid points, {sum(lengths):.2f} um searched", file=sys.stderr)

    normalize_tree_geometry(trees)

    return {
        "schema_version": 1, "units": "um",
        "status": "obstacle-aware late-promotion phase-tree candidate; physical pilot pending",
        "channel_bbox": [0.0, 0.0, 19.32, 112.99],
        "tree_order": order, "trees": trees,
        "constraints": {
            "same_layer_spacing_um": SPACING, "route_width_um": ROUTE_WIDTH,
            "grid_um": STEP, "local_escape_um": ESCAPE_UM,
            "bend_cost_grid_units": 8.0, "via_cost_grid_units": 60.0,
            "allow_u_turns": False, "allow_floating_stubs": False,
            "allow_orphan_vias": False,
            "balance_definition": "common-centroid physical placement plus extracted root-to-leaf RC closure; no artificial meanders",
        },
        "source": {
            "matrix_manifest": str(matrix_path.relative_to(ROOT)),
            "matrix_manifest_sha256": sha256(matrix_path),
            "obstacle_gds": str(gds.relative_to(ROOT)),
            "obstacle_gds_sha256": sha256(gds),
            "planner": str(Path(__file__).relative_to(ROOT)),
            "planner_sha256": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build(args.matrix.resolve(), args.gds.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
