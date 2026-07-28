#!/usr/bin/env python3
"""Plan the eight V3 group-phase trees against the flattened matrix GDS.

This is a deterministic detailed-routing aid, not a generic autorouter.  It
uses the already closed 15-unit matrix GDS as the obstacle source, reserves
0.30 um same-layer spacing around a 0.40 um route, and permits a layer change
only when both Via-3 landing rectangles are clear.  The result is an explicit
segment/via manifest which is subsequently regenerated and checked without
depending on this search algorithm.
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


MATRIX = ROOT / "v3" / "layout" / "channel_matrix_placement.json"
DEFAULT_GDS = ROOT / "build" / "v3" / "channel_matrix_pilot" / "v3_channel_matrix_pilot.gds"
DEFAULT_OUTPUT = ROOT / "v3" / "layout" / "group_phase_trees.json"
TOP = "v3_channel_matrix_pilot"
ORIGIN = (20.0, 20.0)

STEP = 0.05
X_OFFSET = 0.02
Y_OFFSET = 0.00
X_MIN = 0.02
X_MAX = 19.27
Y_MIN = 20.00
Y_MAX = 93.95
ROUTE_WIDTH = 0.40
SPACING = 0.30
SIDE_TRUNK_WIDTH = 0.30

# The two internal roots are an inversion-symmetric pair about x=7.87 um.
# Six remaining roots use the otherwise unused 3.58 um inter-channel band.
ROOTS = {
    "g1_lop": [4.87, 93.05],
    "g1_lon": [10.87, 93.05],
    "g8_lon": [15.82, 93.05],
    # The first gap is 0.70 um because Magic's Via-3 contact tile emits a
    # 0.40 um M4 landing even when the connected trunk itself is 0.30 um.
    "g8_lop": [16.52, 93.05],
    "g4_lon": [17.17, 93.05],
    "g4_lop": [17.82, 93.05],
    "g2_lon": [18.47, 93.05],
    "g2_lop": [19.12, 93.05],
}

SIDE_TRUNK_BOTTOM = {
    "g8_lon": 21.85,
    "g8_lop": 22.65,
    "g4_lon": 37.85,
    "g4_lop": 38.65,
    "g2_lon": 53.85,
    "g2_lop": 54.65,
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


def add_rect(blocked: set[tuple[int, int]], rect: tuple[float, float, float, float], margin: float) -> None:
    x0, y0, x1, y1 = rect
    lo_x = max(IX_MIN, math.ceil((x0 - margin - X_OFFSET) / STEP - 1e-9))
    hi_x = min(IX_MAX, math.floor((x1 + margin - X_OFFSET) / STEP + 1e-9))
    lo_y = max(IY_MIN, math.ceil((y0 - margin - Y_OFFSET) / STEP - 1e-9))
    hi_y = min(IY_MAX, math.floor((y1 + margin - Y_OFFSET) / STEP + 1e-9))
    for gx in range(lo_x, hi_x + 1):
        for gy in range(lo_y, hi_y + 1):
            blocked.add((gx, gy))


def base_obstacles(gds: Path) -> dict[int, set[tuple[int, int]]]:
    structures, database_um = parse_gds(gds)
    rectangles = flatten_rectangles(structures, TOP, database_um)
    output = {0: set(), 1: set()}
    for layer_index, layer in enumerate((MET3, MET4)):
        for raw in rectangles[layer]:
            rect = (
                raw[0] - ORIGIN[0], raw[1] - ORIGIN[1],
                raw[2] - ORIGIN[0], raw[3] - ORIGIN[1],
            )
            # Centre-line exclusion for a 0.40 um route beside existing metal.
            add_rect(output[layer_index], rect, ROUTE_WIDTH / 2.0 + SPACING)
    return output


def net_terminals(matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in matrix["matrix"]["instances"]:
        group = int(instance["group_weight"])
        for polarity in ("lon", "lop"):
            route = instance["local_lo_routes"][polarity]
            root = route["root"]
            # The first 0.70 um is a deliberate same-net continuation of the
            # already closed local merge.  Its endpoint is outside the local
            # route's 0.50 um spacing halo and becomes the detailed-router pin.
            escape = [root[0], round(root[1] + 0.70, 6)]
            result[f"g{group}_{polarity}"].append({
                "unit": instance["name"],
                "local_root": root,
                "escape": escape,
                "layer": 0 if polarity == "lon" else 1,
            })
    for values in result.values():
        values.sort(key=lambda item: (item["escape"][1], item["escape"][0]))
    return dict(result)


def point(value: list[float], layer: int) -> GridPoint:
    return ix(value[0]), iy(value[1]), layer


def manhattan_heuristic(state: State, goal: GridPoint) -> int:
    return abs(state[0] - goal[0]) + abs(state[1] - goal[1]) + (8 if state[2] != goal[2] else 0)


def route_one(
    tree: set[GridPoint], goal: GridPoint, blocked: dict[int, set[tuple[int, int]]],
    net_name: str, reservations: dict[GridPoint, set[str]],
) -> list[GridPoint]:
    """Join one terminal to an existing tree with bend/via-aware A*."""
    queue: list[tuple[int, int, State]] = []
    costs: dict[State, int] = {}
    previous: dict[State, State | None] = {}
    serial = 0
    # Direction 4 means "not yet moving".  Seed only tree boundary points to
    # keep the multi-source queue compact while retaining exact connectivity.
    seeds = []
    for seed in tree:
        gx, gy, layer = seed
        if any((gx + dx, gy + dy, layer) not in tree for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            seeds.append(seed)
    for gx, gy, layer in seeds:
        state = (gx, gy, layer, 4)
        costs[state] = 0
        previous[state] = None
        heapq.heappush(queue, (manhattan_heuristic(state, goal), serial, state))
        serial += 1

    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    final: State | None = None
    while queue:
        _priority, _serial, current = heapq.heappop(queue)
        cost = costs[current]
        gx, gy, layer, old_direction = current
        if (gx, gy, layer) == goal:
            final = current
            break
        for direction, (dx, dy) in enumerate(directions):
            nx, ny = gx + dx, gy + dy
            if not (IX_MIN <= nx <= IX_MAX and IY_MIN <= ny <= IY_MAX):
                continue
            owners = reservations.get((nx, ny, layer), set())
            own_access = bool(owners) and owners <= {net_name}
            if owners - {net_name}:
                continue
            if (nx, ny) in blocked[layer] and not own_access and (nx, ny, layer) != goal:
                continue
            bend = 0 if old_direction in (4, direction) else 5
            candidate = (nx, ny, layer, direction)
            new_cost = cost + 10 + bend
            if new_cost < costs.get(candidate, 1 << 60):
                costs[candidate] = new_cost
                previous[candidate] = current
                estimate = new_cost + 10 * manhattan_heuristic(candidate, goal)
                heapq.heappush(queue, (estimate, serial, candidate))
                serial += 1
        other = 1 - layer
        # Via-3 is intentionally expensive and only legal in a clear patch on
        # both layers.  Goal exception is limited to the goal's own layer.
        other_owners = reservations.get((gx, gy, other), set())
        here_owners = reservations.get((gx, gy, layer), set())
        if (
            not (other_owners - {net_name})
            and not (here_owners - {net_name})
            and ((gx, gy) not in blocked[other] or (other_owners and other_owners <= {net_name}))
            and ((gx, gy) not in blocked[layer] or (here_owners and here_owners <= {net_name}))
        ):
            candidate = (gx, gy, other, 4)
            new_cost = cost + 120
            if new_cost < costs.get(candidate, 1 << 60):
                costs[candidate] = new_cost
                previous[candidate] = current
                estimate = new_cost + 10 * manhattan_heuristic(candidate, goal)
                heapq.heappush(queue, (estimate, serial, candidate))
                serial += 1
    if final is None:
        raise RuntimeError(f"no detailed route to {xy(goal)} on {'M3' if goal[2] == 0 else 'M4'}")

    states = []
    cursor: State | None = final
    while cursor is not None:
        states.append(cursor)
        cursor = previous[cursor]
    states.reverse()
    return [(gx, gy, layer) for gx, gy, layer, _direction in states]


def compress(path: list[GridPoint]) -> tuple[list[dict[str, Any]], list[list[float]]]:
    segments: list[dict[str, Any]] = []
    vias: list[list[float]] = []
    start = path[0]
    prior = path[0]
    prior_direction: tuple[int, int, int] | None = None
    for current in path[1:]:
        if current[2] != prior[2]:
            if start != prior:
                segments.append({
                    "from": xy(start), "to": xy(prior),
                    "layer": "metal3" if prior[2] == 0 else "metal4",
                    "width_um": ROUTE_WIDTH,
                })
            vias.append(xy(current))
            start = current
            prior = current
            prior_direction = None
            continue
        direction = (current[0] - prior[0], current[1] - prior[1], current[2])
        if prior_direction is not None and direction != prior_direction:
            segments.append({
                "from": xy(start), "to": xy(prior),
                "layer": "metal3" if prior[2] == 0 else "metal4",
                "width_um": ROUTE_WIDTH,
            })
            start = prior
        prior_direction = direction
        prior = current
    if start != prior:
        segments.append({
            "from": xy(start), "to": xy(prior),
            "layer": "metal3" if prior[2] == 0 else "metal4",
            "width_um": ROUTE_WIDTH,
        })
    return segments, vias


def mark_path(blocked: dict[int, set[tuple[int, int]]], path: Iterable[GridPoint]) -> None:
    radius = int(math.floor((ROUTE_WIDTH + SPACING - 1e-9) / STEP))
    for gx, gy, layer in path:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) * STEP < ROUTE_WIDTH + SPACING - 1e-9 and abs(dy) * STEP < ROUTE_WIDTH + SPACING - 1e-9:
                    blocked[layer].add((gx + dx, gy + dy))


def grid_line(first: GridPoint, second: GridPoint) -> list[GridPoint]:
    if first[2] != second[2]:
        raise ValueError("a fixed grid line cannot change layer")
    if first[0] != second[0] and first[1] != second[1]:
        raise ValueError(f"non-Manhattan fixed grid line: {first} -> {second}")
    dx = 0 if first[0] == second[0] else (1 if second[0] > first[0] else -1)
    dy = 0 if first[1] == second[1] else (1 if second[1] > first[1] else -1)
    count = max(abs(second[0] - first[0]), abs(second[1] - first[1]))
    return [(first[0] + index * dx, first[1] + index * dy, first[2]) for index in range(count + 1)]


def reserve_line(
    reservations: dict[GridPoint, set[str]], name: str, path: Iterable[GridPoint],
    existing_width: float,
) -> None:
    # A new 0.40 um route or Via-3 M4 landing may approach a fixed trunk down
    # to half(new)+spacing+half(existing).  Equality is legal.
    clearance = ROUTE_WIDTH / 2.0 + SPACING + existing_width / 2.0
    radius = int(math.floor((clearance - 1e-9) / STEP))
    for gx, gy, layer in path:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) * STEP < clearance - 1e-9 and abs(dy) * STEP < clearance - 1e-9:
                    reservations.setdefault((gx + dx, gy + dy, layer), set()).add(name)


def add_manual_segment(
    tree: set[GridPoint], segments: list[dict[str, Any]], first: list[float],
    second: list[float], layer: int, width: float = ROUTE_WIDTH,
) -> None:
    tree.update(grid_line(point(first, layer), point(second, layer)))
    segments.append({
        "from": first, "to": second,
        "layer": "metal3" if layer == 0 else "metal4",
        "width_um": width,
    })


def add_manual_via(tree: set[GridPoint], vias: list[list[float]], at: list[float]) -> None:
    tree.add(point(at, 0))
    tree.add(point(at, 1))
    vias.append(at)


def add_m3_branch(
    tree: set[GridPoint], segments: list[dict[str, Any]], vias: list[list[float]],
    roots: list[list[float]], branch_y: float, trunk_x: float,
    local_layer: int,
) -> None:
    left = min(point_[0] for point_ in roots)
    right = max(max(point_[0] for point_ in roots), trunk_x)
    add_manual_segment(tree, segments, [left, branch_y], [right, branch_y], 0)
    add_manual_via(tree, vias, [trunk_x, branch_y])
    for root in roots:
        if local_layer == 0:
            if not math.isclose(root[1], branch_y):
                add_manual_segment(tree, segments, root, [root[0], branch_y], 0)
        else:
            if not math.isclose(root[1], branch_y):
                add_manual_segment(tree, segments, root, [root[0], branch_y], 1)
            add_manual_via(tree, vias, [root[0], branch_y])


def build(matrix_path: Path, gds: Path) -> dict[str, Any]:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    terminals = net_terminals(matrix)
    blocked = base_obstacles(gds)
    reservations: dict[GridPoint, set[str]] = {}
    for reserved_name, reserved_terminals in terminals.items():
        for terminal in reserved_terminals:
            centre_x = ix(terminal["escape"][0])
            root_y = iy(terminal["local_root"][1])
            escape_y = iy(terminal["escape"][1])
            for layer in (0, 1):
                for gx in range(centre_x - 3, centre_x + 4):
                    for gy in range(root_y, escape_y + 5):
                        key = (gx, gy, layer)
                        reservations.setdefault(key, set()).add(reserved_name)

    fixed_trees: dict[str, set[GridPoint]] = {}
    fixed_segments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Reserve every side trunk before any branch is searched.  This prevents
    # the first net from consuming a later net's only vertical corridor.
    for reserved_name, bottom in SIDE_TRUNK_BOTTOM.items():
        root = point(ROOTS[reserved_name], 1)
        lower = point([ROOTS[reserved_name][0], bottom], 1)
        path = grid_line(root, lower)
        fixed_trees[reserved_name] = set(path)
        reserve_line(reservations, reserved_name, path, SIDE_TRUNK_WIDTH)
        fixed_segments[reserved_name].append({
            "from": ROOTS[reserved_name],
            "to": [ROOTS[reserved_name][0], bottom],
            "layer": "metal4",
            "width_um": SIDE_TRUNK_WIDTH,
            "role": "reserved_vertical_trunk",
        })
    trees: dict[str, Any] = {}
    # Fixed pair branches close first.  The only searched leaf paths are the
    # two G8 centre taps, which must negotiate the already reserved G4 branch
    # tracks and the two internal G1 trunks.
    order = [
        "g1_lop", "g1_lon", "g2_lon", "g2_lop",
        "g4_lon", "g4_lop", "g8_lop", "g8_lon",
    ]
    for name in order:
        polarity = name.rsplit("_", 1)[1]
        root = point(ROOTS[name], 1)
        tree = set(fixed_trees.get(name, {root}))
        paths: list[dict[str, Any]] = []
        # Alternate equal-radius leaves around the common centroid.
        leaves = sorted(
            terminals[name],
            key=lambda item: (
                -abs(item["escape"][1] - 53.55),
                -abs(item["escape"][0] - 7.87),
                item["escape"][1], item["escape"][0],
            ),
        )
        if name in ("g1_lop", "g1_lon"):
            # Keep the G1-LON Via-3 M3 landing 0.31 um away from the mirrored
            # G2 local escape that begins at x=10.79.
            target = [4.87, 53.95] if name == "g1_lop" else [10.17, 53.15]
            backbone = route_one(tree, point(target, 1), blocked, name, reservations)
            tree.update(backbone)
            segments, vias = compress(backbone)
            local = leaves[0]["local_root"]
            if name == "g1_lop":
                add_manual_segment(tree, segments, local, target, 1)
            else:
                add_manual_segment(tree, segments, local, target, 0)
                add_manual_via(tree, vias, target)
            paths.append({
                "terminal": leaves[0], "role": "internal_single-leaf_tree",
                "segments": segments, "via3_points": vias,
            })
        elif name in ("g2_lon", "g2_lop"):
            segments: list[dict[str, Any]] = []
            vias: list[list[float]] = []
            branch_y = 53.90 if name.endswith("lon") else 54.60
            add_m3_branch(
                tree, segments, vias,
                [item["local_root"] for item in leaves], branch_y,
                ROOTS[name][0], 0 if name.endswith("lon") else 1,
            )
            paths.append({
                "terminal": "symmetric_outer_pair", "role": "fixed_pair_branch",
                "segments": segments, "via3_points": vias,
            })
        elif name in ("g4_lon", "g4_lop"):
            grouped: dict[float, list[list[float]]] = defaultdict(list)
            for item in leaves:
                grouped[item["local_root"][1]].append(item["local_root"])
            for local_y, roots in sorted(grouped.items()):
                segments = []
                vias = []
                branch_y = local_y + (0.70 if name.endswith("lon") else 0.60)
                add_m3_branch(
                    tree, segments, vias, roots, round(branch_y, 6),
                    ROOTS[name][0], 0 if name.endswith("lon") else 1,
                )
                paths.append({
                    "terminal": [item for item in leaves if item["local_root"][1] == local_y],
                    "role": "fixed_symmetric_row_pair",
                    "segments": segments, "via3_points": vias,
                })
        elif name == "g8_lop":
            grouped = defaultdict(list)
            for item in leaves:
                grouped[item["local_root"][1]].append(item["local_root"])
            for local_y, roots in sorted(grouped.items()):
                segments = []
                vias = []
                branch_y = local_y + (0.70 if len(roots) == 3 else 1.30)
                add_m3_branch(tree, segments, vias, roots, round(branch_y, 6), ROOTS[name][0], 1)
                paths.append({
                    "terminal": [item for item in leaves if item["local_root"][1] == local_y],
                    "role": "fixed_outer_row_or_centre_tap",
                    "segments": segments, "via3_points": vias,
                })
        elif name == "g8_lon":
            grouped = defaultdict(list)
            for item in leaves:
                grouped[item["local_root"][1]].append(item)
            # Top and bottom triples are clean M3 row branches.
            centre_items = []
            for local_y, items in sorted(grouped.items()):
                if len(items) == 3:
                    segments = []
                    vias = []
                    branch_y = round(local_y + 0.70, 6)
                    landing_x = 15.87
                    roots = [item["local_root"] for item in items]
                    add_manual_segment(tree, segments, [min(root[0] for root in roots), branch_y], [landing_x, branch_y], 0)
                    for local_root in roots:
                        add_manual_segment(tree, segments, local_root, [local_root[0], branch_y], 0)
                    add_manual_segment(tree, segments, [landing_x, branch_y], [ROOTS[name][0], branch_y], 1, SIDE_TRUNK_WIDTH)
                    paths.append({
                        "terminal": items, "role": "fixed_symmetric_outer_row",
                        "segments": segments,
                        "compact_via3_points": [[landing_x, branch_y]],
                        "via3_points": vias,
                    })
                else:
                    centre_items.extend(items)
            # The centre taps leave on M4 at their local-root Y coordinate, so
            # they would have to cross both a G4 M3 row branch and an internal
            # G1 M4 trunk.  A short named M2 bridge in the quiet inter-row gap
            # returns to M3 before the side bank, so there is no stacked-via
            # island, dead landing, or artificial length loop.
            for terminal in sorted(centre_items, key=lambda item: item["local_root"][1]):
                segments = []
                vias = []
                local = terminal["local_root"]
                # The mirrored right-column local LON merge ends at x=15.15.
                # Return beyond its spacing halo, then join the innermost M4
                # trunk with a conducting 0.18 um branch (not a dead stub).
                m3_return = [15.87, local[1]]
                segments.append({
                    "from": local, "to": m3_return,
                    "layer": "metal2", "width_um": 0.30,
                })
                add_manual_segment(tree, segments, m3_return, [ROOTS[name][0], local[1]], 1, SIDE_TRUNK_WIDTH)
                paths.append({
                    "terminal": terminal, "role": "named_m2_centre_tap_bridge",
                    "segments": segments,
                    "via2_points": [local],
                    "compact_via2_points": [m3_return],
                    "compact_via3_points": [m3_return],
                    "via3_points": vias,
                })
        else:
            raise AssertionError(name)
        # Reserve this complete net before planning the next one.
        mark_path(blocked, tree)
        trees[name] = {
            "group": int(name[1]),
            "polarity": polarity,
            "root": ROOTS[name],
            "root_layer": "metal4",
            "terminals": terminals[name],
            "paths": paths,
            "fixed_segments": fixed_segments.get(name, []),
            "grid_point_count": len(tree),
        }
        print(f"planned {name}: {len(leaves)} leaves, {len(tree)} grid points", file=sys.stderr)
    return {
        "schema_version": 1,
        "units": "um",
        "status": "detailed route candidate; physical pilot pending",
        "channel_bbox": [0.0, 0.0, 19.32, 93.99],
        "tree_order": order,
        "trees": trees,
        "constraints": {
            "same_layer_spacing_um": SPACING,
            "route_width_um": ROUTE_WIDTH,
            "grid_um": STEP,
            "allow_u_turns": False,
            "allow_floating_stubs": False,
            "allow_orphan_vias": False,
            "maximum_extracted_leaf_skew_ps": 100.0,
            "balance_definition": "common-centroid mirror pairs plus extracted RC/edge-skew closure; no artificial meanders",
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
    data = build(args.matrix.resolve(), args.gds.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
