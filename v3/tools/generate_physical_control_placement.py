#!/usr/bin/env python3
"""Generate the deterministic production placement for the shared V3 controller.

The placement deliberately reuses the physical rules proven by V2, while its
data flow follows the V3 interface.  A compact 32-bit active/shift bank occupies
the east side of the reserved digital region.  Final vector and phase drivers
face west toward the frozen analog macros, and the remaining global logic is
legalized from actual net connectivity rather than alphabetical cell order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

SITE = 0.46
ROW = 2.72
X0 = 181.24
X1 = 319.70
Y0 = 171.36
ROW_COUNT = 17
GLOBAL_X1 = 245.18
CONFIG_X0 = 245.64
MAX_TAP_PITCH = 13.80
POWER_PINS = {"VGND", "VPWR", "VPB", "VNB"}
INDEX_RE = re.compile(r"\[([0-9]+)\]$")
OFFICIAL_PIN_ORDER = [
    "cfg_latch",
    "cfg_data",
    "cfg_clk",
    "channel_enable[3]",
    "channel_enable[2]",
    "channel_enable[1]",
    "channel_enable[0]",
    "raw_mode",
    "beam_select[2]",
    "beam_select[1]",
    "beam_select[0]",
    "rst_n",
    "clk",
    "ena",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snap_site(value: float) -> float:
    return round(value / SITE) * SITE


def row_orientation(row: int, horizontal_mirror: bool = False) -> str:
    if row % 2 == 0:
        return "MY" if horizontal_mirror else "R0"
    return "R180" if horizontal_mirror else "MX"


def transform_point(
    point: tuple[float, float], width: float, height: float, orientation: str
) -> tuple[float, float]:
    x, y = point
    if orientation == "R0":
        return x, y
    if orientation == "MX":
        return x, height - y
    if orientation == "MY":
        return width - x, y
    if orientation == "R180":
        return width - x, height - y
    raise ValueError(f"unsupported orientation {orientation}")


def access_center(spec: dict[str, Any], pin: str) -> tuple[float, float, str]:
    accesses = spec["pins"][pin]["access_rects"]
    rank = {"met2": 3, "met1": 2, "li1": 1}
    best_rank = max(rank.get(item["layer"], 0) for item in accesses)
    candidates = [item for item in accesses if rank.get(item["layer"], 0) == best_rank]
    width, height = map(float, spec["size_um"])

    def key(item: dict[str, Any]) -> tuple[float, float, float]:
        x0, y0, x1, y1 = map(float, item["rect_um"])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return (
            (cx - width / 2.0) ** 2 + (cy - height / 2.0) ** 2,
            -(x1 - x0) * (y1 - y0),
            cx,
        )

    chosen = min(candidates, key=key)
    x0, y0, x1, y1 = map(float, chosen["rect_um"])
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, chosen["layer"]


class V3ControllerPlacer:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self.mapping = mapping
        self.library = mapping["library"]
        self.cells = {item["instance"]: item for item in mapping["cells"]}
        self.placements: dict[str, dict[str, Any]] = {}
        self.row_cells: dict[int, list[str]] = defaultdict(list)
        self.fixed_instances: set[str] = set()
        self.signal_anchors = self._signal_anchors()

    @staticmethod
    def _signal_anchors() -> dict[str, tuple[float, float]]:
        # Exact TinyTapeout top-pin locations inherited from the V2 floorplan.
        anchors = {
            "clk": (143.98, 225.26),
            "rst_n": (141.22, 225.26),
            "ena": (146.74, 225.26),
            "beam_select[0]": (138.46, 225.26),
            "beam_select[1]": (135.70, 225.26),
            "beam_select[2]": (132.94, 225.26),
            "direct_async[4]": (130.18, 225.26),
            "raw_mode": (130.18, 225.26),
            "channel_enable[0]": (127.42, 225.26),
            "channel_enable[1]": (124.66, 225.26),
            "channel_enable[2]": (121.90, 225.26),
            "channel_enable[3]": (119.14, 225.26),
            "cfg_clk": (116.38, 225.26),
            "cfg_data": (113.62, 225.26),
            "cfg_latch": (110.86, 225.26),
            "mixers_blank": (159.14, 179.01),
        }
        # Existing balanced-tree roots.  The mapping between phase_wave and
        # physical phase name comes directly from quadrature_generator.v.
        anchors.update({
            "phase_wave[0]": (111.26, 200.20),
            "phase_wave[1]": (110.26, 198.40),
            "phase_wave[2]": (109.26, 196.60),
            "phase_wave[3]": (108.26, 194.80),
        })
        channel_x = (155.14, 135.82, 116.50, 97.18)
        for channel, x in enumerate(channel_x):
            for local_bit in range(8):
                anchors[f"group_codes[{8 * channel + local_bit}]"] = (
                    x,
                    187.01 - 0.80 * local_bit,
                )
            anchors[f"channel_bias_enable[{channel}]"] = (x, 179.81)
        return anchors

    def output_driver(self, net: str) -> tuple[str, str]:
        matches: list[tuple[str, str]] = []
        for cell in self.cells.values():
            spec = self.library[cell["short_cell"]]
            for pin, pin_net in cell["pins"].items():
                if pin_net != net:
                    continue
                if spec["pins"].get(pin, {}).get("direction") == "output":
                    matches.append((cell["instance"], pin))
        if len(matches) != 1:
            raise ValueError(f"expected one driver for {net}, found {matches}")
        return matches[0]

    def q_cell(self, net: str) -> dict[str, Any]:
        matches = [cell for cell in self.cells.values() if cell["pins"].get("Q") == net]
        if len(matches) != 1:
            raise ValueError(f"expected one Q driver for {net}, found {len(matches)}")
        return matches[0]

    def add(
        self,
        instance: str,
        x: float,
        row: int,
        orientation: str,
        rationale: str,
        region: str,
        fixed: bool = False,
    ) -> None:
        if instance in self.placements:
            raise ValueError(f"duplicate placement for {instance}")
        if row < 0 or row >= ROW_COUNT:
            raise ValueError(f"{instance}: illegal row {row}")
        cell = self.cells[instance]
        width, height = map(float, cell["size_um"])
        x = snap_site(x)
        y = Y0 + row * ROW
        rx0, rx1 = (X0, GLOBAL_X1) if region == "global_control_core" else (CONFIG_X0, X1)
        if x < rx0 - 1e-9 or x + width > rx1 + 1e-9:
            raise ValueError(f"{instance}: leaves {region}: x={x}, width={width}")
        box = [x, y, x + width, y + height]
        for other_name in self.row_cells[row]:
            other = self.placements[other_name]
            ox0, _, ox1, _ = map(float, other["bbox_um"])
            if x < ox1 - 1e-9 and x + width > ox0 + 1e-9:
                raise ValueError(f"{instance} overlaps {other_name}")
        self.placements[instance] = {
            "instance": instance,
            "cell": cell["cell"],
            "short_cell": cell["short_cell"],
            "role": cell["role"],
            "region": region,
            "row": row,
            "origin_um": [round(x, 6), round(y, 6)],
            "bbox_um": [round(v, 6) for v in box],
            "orientation": orientation,
            "rationale": rationale,
        }
        self.row_cells[row].append(instance)
        if fixed:
            self.fixed_instances.add(instance)

    def add_pair(
        self,
        prefix: str,
        x: float,
        row: int,
        output_left: bool,
        rationale: str,
        region: str,
    ) -> float:
        mux_name = f"{prefix}/enable_mux"
        ff_name = f"{prefix}/state_ff"
        mux_width = float(self.cells[mux_name]["size_um"][0])
        ff_width = float(self.cells[ff_name]["size_um"][0])
        if output_left:
            self.add(
                ff_name, x, row, row_orientation(row, True), rationale, region, True
            )
            mux_x = snap_site(x + ff_width + SITE)
            self.add(
                mux_name, mux_x, row, row_orientation(row), rationale, region, True
            )
            return mux_x + mux_width
        self.add(
            mux_name, x, row, row_orientation(row, True), rationale, region, True
        )
        ff_x = snap_site(x + mux_width + SITE)
        self.add(
            ff_name, ff_x, row, row_orientation(row), rationale, region, True
        )
        return ff_x + ff_width

    def storage_prefixes(self, role: str) -> dict[int, str]:
        result: dict[int, str] = {}
        for cell in self.cells.values():
            if cell["role"] != role or not cell["instance"].endswith("/state_ff"):
                continue
            q_net = cell["pins"]["Q"]
            match = INDEX_RE.search(q_net)
            if not match:
                raise ValueError(f"cannot infer storage index from {q_net}")
            result[int(match.group(1))] = cell["instance"].rsplit("/", 1)[0]
        if set(result) != set(range(32)):
            raise ValueError(f"{role}: incomplete storage bank")
        return result

    def place_configuration_bank(self) -> None:
        active = self.storage_prefixes("active_vector_storage")
        shift = self.storage_prefixes("serial_shift_storage")
        block_x = (247.02, 283.82)
        for row in range(16):
            bits = [2 * row, 2 * row + 1]
            # The shift chain enters bit 31 and descends to bit 0.  Alternating
            # the two slots makes every inter-row transition vertical and each
            # intra-row transition horizontal, with no U-turns.
            if row % 2 == 0:
                bits.reverse()
            for slot, bit in enumerate(bits):
                x = block_x[slot]
                active_end = self.add_pair(
                    active[bit], x, row, True,
                    f"active vector bit {bit}; Q faces west toward its final driver",
                    "config_storage_bank",
                )
                shift_x = snap_site(active_end + SITE)
                self.add_pair(
                    shift[bit], shift_x, row, bool(row % 2),
                    f"serial bit {bit}; serpentine Q faces the next lower stage",
                    "config_storage_bank",
                )

    def orientation_for_output(self, instance: str, pin: str, row: int) -> str:
        cell = self.cells[instance]
        spec = self.library[cell["short_cell"]]
        local_x, local_y, _ = access_center(spec, pin)
        width, height = map(float, spec["size_um"])
        normal = row_orientation(row)
        mirrored = row_orientation(row, True)
        nx, _ = transform_point((local_x, local_y), width, height, normal)
        mx, _ = transform_point((local_x, local_y), width, height, mirrored)
        return mirrored if mx < nx else normal

    def place_output_band(self) -> None:
        for bit in range(32):
            row = bit // 2
            slot = bit % 2
            instance, pin = self.output_driver(f"group_codes[{bit}]")
            x = 192.28 + slot * 5.06
            self.add(
                instance,
                x,
                row,
                self.orientation_for_output(instance, pin, row),
                f"final group-code bit {bit} driver faces the west routing corridor",
                "global_control_core",
                True,
            )

        for output_row, net in enumerate(
            [f"channel_bias_enable[{i}]" for i in range(4)] + ["mixers_blank"]
        ):
            instance, pin = self.output_driver(net)
            self.add(
                instance,
                X0,
                output_row,
                self.orientation_for_output(instance, pin, output_row),
                f"final {net} driver faces the west channel-control corridor",
                "global_control_core",
                True,
            )

        phase_rows = {3: 8, 2: 9, 1: 10, 0: 11}
        for phase, row in phase_rows.items():
            net = f"phase_wave[{phase}]"
            instance, pin = self.output_driver(net)
            self.add(
                instance,
                X0,
                row,
                self.orientation_for_output(instance, pin, row),
                f"{net} final driver row-aligned with its balanced-tree root",
                "global_control_core",
                True,
            )

    def _fanout_instances(self, net: str) -> list[str]:
        return sorted(
            cell["instance"]
            for cell in self.cells.values()
            if cell["pins"].get("A") == net
            and cell["instance"].startswith(f"physical_fanout/{net}/")
        )

    def _place_linear_bank(
        self,
        instances: list[str],
        start_x: float,
        row: int,
        region: str,
        rationale: str,
    ) -> float:
        x = snap_site(start_x)
        for index, instance in enumerate(instances):
            self.add(
                instance,
                x,
                row,
                row_orientation(row, bool(index % 2)),
                rationale,
                region,
                True,
            )
            x = snap_site(x + float(self.cells[instance]["size_um"][0]) + SITE)
        return x

    def place_input_synchronizers(self) -> None:
        sync_nets = {
            0: "direct_sync[0]",
            1: "beam_sync[0]",
            2: "beam_sync[1]",
            3: "beam_sync[2]",
            4: "direct_sync[4]",
            5: "channel_enable_sync[0]",
            6: "channel_enable_sync[1]",
            7: "channel_enable_sync[2]",
            8: "channel_enable_sync[3]",
        }
        bands = [
            ((5, 4, 3), 16, 15),
            ((8, 7, 6), 14, 13),
            ((2, 1, 0), 12, 11),
        ]
        for bits, meta_row, sync_row in bands:
            for slot, bit in enumerate(bits):
                x = 210.68 + slot * 9.66
                meta = self.q_cell(f"direct_meta[{bit}]")
                sync = self.q_cell(sync_nets[bit])
                self.add(
                    meta["instance"], x, meta_row, row_orientation(meta_row),
                    f"pin-ordered first synchronizer stage for direct bit {bit}",
                    "global_control_core", True,
                )
                self.add(
                    sync["instance"], x, sync_row, row_orientation(sync_row),
                    f"second synchronizer stage aligned below direct bit {bit}",
                    "global_control_core", True,
                )

        config_fanout = self._fanout_instances("cfg_latch")
        config_fanout += self._fanout_instances("cfg_clk")
        self._place_linear_bank(
            config_fanout,
            X0,
            16,
            "global_control_core",
            "northwest ordered configuration ingress fanout",
        )
        main_fanout = self._fanout_instances("rst_n")
        main_fanout += self._fanout_instances("clk")
        end_x = self._place_linear_bank(
            main_fanout,
            CONFIG_X0,
            16,
            "config_storage_bank",
            "northeast ordered reset/clock ingress fanout",
        )
        if end_x > 284.30:
            raise ValueError(f"pin-aligned ingress bank ends at {end_x:.3f} um")

    def cell_center(self, instance: str) -> tuple[float, float]:
        box = self.placements[instance]["bbox_um"]
        return (float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2

    def ideal_positions(self, remaining: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
        center = ((X0 + GLOBAL_X1) / 2, Y0 + ROW_COUNT * ROW / 2)
        positions = {name: self.cell_center(name) for name in self.placements}
        positions.update({cell["instance"]: center for cell in remaining})
        remaining_names = {cell["instance"] for cell in remaining}
        for _ in range(160):
            updated: dict[str, tuple[float, float]] = {}
            for cell in remaining:
                samples: list[tuple[float, float, float]] = []
                for pin, net in cell["pins"].items():
                    if pin in POWER_PINS:
                        continue
                    endpoints = self.mapping["nets"].get(net, [])
                    weight = 1.0 / max(1, len(endpoints) - 1)
                    if net in self.signal_anchors:
                        ax, ay = self.signal_anchors[net]
                        samples.append((ax, ay, 2.5 * weight))
                    for endpoint in endpoints:
                        other = endpoint["instance"]
                        if other == cell["instance"] or other not in positions:
                            continue
                        ox, oy = positions[other]
                        samples.append((ox, oy, weight))
                if not samples:
                    samples = [(center[0], center[1], 1.0)]
                total = sum(item[2] for item in samples)
                x = sum(item[0] * item[2] for item in samples) / total
                y = sum(item[1] * item[2] for item in samples) / total
                updated[cell["instance"]] = (
                    min(GLOBAL_X1 - SITE, max(X0, x)),
                    min(Y0 + (ROW_COUNT - 0.5) * ROW, max(Y0 + 0.5 * ROW, y)),
                )
            positions.update(updated)
        return {name: positions[name] for name in remaining_names}

    def occupied_sites(self, row: int, guard: bool = False) -> set[int]:
        first = round(X0 / SITE)
        occupied: set[int] = set()
        for name in self.row_cells[row]:
            x0, _, x1, _ = map(float, self.placements[name]["bbox_um"])
            lo = round(x0 / SITE) - first
            hi = round(x1 / SITE) - first
            occupied.update(range(lo, hi))
            if guard:
                occupied.update((lo - 1, hi))
        return occupied

    def place_global_residual(self) -> None:
        remaining = [
            cell for cell in self.cells.values()
            if cell["region"] == "global_control_core"
            and cell["instance"] not in self.placements
        ]
        ideals = self.ideal_positions(remaining)
        degree = {
            cell["instance"]: sum(
                len(self.mapping["nets"].get(net, []))
                for pin, net in cell["pins"].items() if pin not in POWER_PINS
            )
            for cell in remaining
        }
        # Wide sequential cells are hardest to legalize and are therefore
        # assigned first; connectivity degree breaks equal-width ties.
        remaining.sort(key=lambda cell: (
            -float(cell["size_um"][0]), -degree[cell["instance"]], cell["instance"]
        ))
        global_first = round(X0 / SITE)
        global_last = round(GLOBAL_X1 / SITE)
        for cell in remaining:
            width_sites = round(float(cell["size_um"][0]) / SITE)
            target_x, target_y = ideals[cell["instance"]]
            target_row = round((target_y - Y0) / ROW)
            candidates: list[tuple[float, int, int]] = []
            for row in range(ROW_COUNT):
                blocked = self.occupied_sites(row, guard=True)
                used_width = sum(
                    float(self.placements[name]["bbox_um"][2])
                    - float(self.placements[name]["bbox_um"][0])
                    for name in self.row_cells[row]
                    if self.placements[name]["region"] == "global_control_core"
                )
                if used_width + width_sites * SITE > 48.30 + 1e-9:
                    continue
                for start in range(global_first, global_last - width_sites + 1):
                    local = start - global_first
                    if any(index in blocked for index in range(local, local + width_sites)):
                        continue
                    x = start * SITE
                    score = (
                        6.0 * abs(row - target_row)
                        + abs((x + width_sites * SITE / 2) - target_x)
                        + 2.0 * used_width
                    )
                    candidates.append((score, row, start))
            if not candidates:
                raise ValueError(f"cannot legalize {cell['instance']}")
            _, row, start = min(candidates)
            self.add(
                cell["instance"], start * SITE, row, row_orientation(row),
                "connectivity-relaxed global logic legalized on the nearest open site",
                "global_control_core",
            )

    def orient_residual_cells(self) -> dict[str, Any]:
        candidates = [
            name for name, item in self.placements.items()
            if item["rationale"].startswith("connectivity-relaxed")
        ]
        mirror = {"R0": "MY", "MY": "R0", "MX": "R180", "R180": "MX"}

        def pin_point(instance: str, pin: str, orientation: str) -> tuple[float, float]:
            cell = self.cells[instance]
            spec = self.library[cell["short_cell"]]
            px, py, _ = access_center(spec, pin)
            width, height = map(float, spec["size_um"])
            px, py = transform_point((px, py), width, height, orientation)
            ox, oy = map(float, self.placements[instance]["origin_um"])
            return ox + px, oy + py

        def score(instance: str, orientation: str) -> float:
            cell = self.cells[instance]
            total = 0.0
            for pin, net in cell["pins"].items():
                if pin in POWER_PINS:
                    continue
                peers: list[tuple[float, float]] = []
                for endpoint in self.mapping["nets"].get(net, []):
                    other = endpoint["instance"]
                    if other == instance or other not in self.placements:
                        continue
                    peers.append(self.cell_center(other))
                if net in self.signal_anchors:
                    peers.append(self.signal_anchors[net])
                if not peers:
                    continue
                tx = statistics.median(point[0] for point in peers)
                ty = statistics.median(point[1] for point in peers)
                px, py = pin_point(instance, pin, orientation)
                total += (abs(px - tx) + abs(py - ty)) / len(peers)
            return total

        initial = sum(score(name, self.placements[name]["orientation"]) for name in candidates)
        changed = 0
        for name in candidates:
            current = self.placements[name]["orientation"]
            alternative = mirror[current]
            if score(name, alternative) + 0.05 < score(name, current):
                self.placements[name]["orientation"] = alternative
                changed += 1
        final = sum(score(name, self.placements[name]["orientation"]) for name in candidates)
        result = {
            "eligible_cells": len(candidates),
            "changed_cells": changed,
            "initial_pin_demand_um": initial,
            "final_pin_demand_um": final,
            "improvement_um": initial - final,
            "improvement_fraction": 0.0 if initial == 0 else 1.0 - final / initial,
        }
        return result

    def add_taps_and_fillers(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        first = round(X0 / SITE)
        last = round(X1 / SITE)
        maximum_sites = round(MAX_TAP_PITCH / SITE)
        taps: list[dict[str, Any]] = []
        fillers: list[dict[str, Any]] = []
        tap_cell = "sky130_fd_sc_hd__tapvpwrvgnd_1"
        fill_cell = "sky130_fd_sc_hd__fill_1"
        for row in range(ROW_COUNT):
            occupied = self.occupied_sites(row)
            free = [site for site in range(last - first) if site not in occupied]
            chosen: list[int] = []
            cursor = 0
            while last - first - cursor > maximum_sites:
                possible = [site for site in free if cursor <= site <= cursor + maximum_sites]
                if not possible:
                    raise ValueError(f"row {row}: no well-tap site after site {cursor}")
                site = max(possible)
                if chosen and site <= chosen[-1]:
                    raise ValueError(f"row {row}: tap insertion stalled")
                chosen.append(site)
                free.remove(site)
                cursor = site
            if not chosen or last - first - chosen[-1] > maximum_sites:
                site = max(free)
                chosen.append(site)
                free.remove(site)
            y = Y0 + row * ROW
            for index, local_site in enumerate(chosen):
                x = (first + local_site) * SITE
                taps.append({
                    "instance": f"TAP_V3_R{row:02d}_{index:02d}",
                    "cell": tap_cell,
                    "short_cell": "tapvpwrvgnd",
                    "role": "well_tap",
                    "region": "shared_control",
                    "row": row,
                    "origin_um": [round(x, 6), round(y, 6)],
                    "bbox_um": [round(x, 6), round(y, 6), round(x + SITE, 6), round(y + ROW, 6)],
                    "orientation": row_orientation(row),
                    "rationale": "explicit V2-qualified well/substrate tap pitch",
                })
            for index, local_site in enumerate(free):
                x = (first + local_site) * SITE
                fillers.append({
                    "instance": f"FILL_V3_R{row:02d}_{index:04d}",
                    "cell": fill_cell,
                    "short_cell": "fill",
                    "role": "power_filler",
                    "region": "shared_control",
                    "row": row,
                    "origin_um": [round(x, 6), round(y, 6)],
                    "bbox_um": [round(x, 6), round(y, 6), round(x + SITE, 6), round(y + ROW, 6)],
                    "orientation": row_orientation(row),
                    "rationale": "foundry filler closes well and M1 rail continuity",
                })
        return taps, fillers

    def attach_pin_access(self) -> None:
        for name, placement in self.placements.items():
            cell = self.cells[name]
            spec = self.library[cell["short_cell"]]
            ox, oy = map(float, placement["origin_um"])
            width, height = map(float, spec["size_um"])
            pins: dict[str, Any] = {}
            for pin, net in cell["pins"].items():
                if pin in POWER_PINS:
                    continue
                px, py, layer = access_center(spec, pin)
                px, py = transform_point((px, py), width, height, placement["orientation"])
                pins[pin] = {
                    "net": net,
                    "layer": layer,
                    "point_um": [round(ox + px, 6), round(oy + py, 6)],
                }
            placement["pin_access"] = pins

    def hpwl(self) -> float:
        total = 0.0
        for net, endpoints in self.mapping["nets"].items():
            points = [
                self.cell_center(item["instance"])
                for item in endpoints if item["instance"] in self.placements
            ]
            if net in self.signal_anchors:
                points.append(self.signal_anchors[net])
            if len(points) > 1:
                total += max(x for x, _ in points) - min(x for x, _ in points)
                total += max(y for _, y in points) - min(y for _, y in points)
        return total

    def result(self) -> dict[str, Any]:
        self.place_configuration_bank()
        self.place_output_band()
        self.place_input_synchronizers()
        self.place_global_residual()
        missing = set(self.cells) - set(self.placements)
        if missing:
            raise ValueError(f"unplaced mapped cells: {sorted(missing)}")
        orientation_audit = self.orient_residual_cells()
        self.attach_pin_access()
        taps, fillers = self.add_taps_and_fillers()
        placed = sorted(
            self.placements.values(), key=lambda item: (item["row"], item["origin_um"][0])
        )
        role_counts = Counter(item["role"] for item in placed)
        result = {
            "schema_version": 1,
            "units": "um",
            "status": "pre-route production pin-aligned placement",
            "top_cell": "v3_physical_control_placed",
            "region": {
                "bbox_um": [X0, Y0, X1, Y0 + ROW_COUNT * ROW],
                "row_count": ROW_COUNT,
                "site_width_um": SITE,
                "row_height_um": ROW,
                "global_bbox_um": [X0, Y0, GLOBAL_X1, Y0 + ROW_COUNT * ROW],
                "configuration_bbox_um": [CONFIG_X0, Y0, X1, Y0 + ROW_COUNT * ROW],
            },
            "policy": {
                "source_architecture": "V2 safe controller physical pattern with V3 payload",
                "one_shared_controller": True,
                "duplicated_quadrature_generators": False,
                "configuration_topology": "32-bit two-slot serpentine shift/active bank",
                "phase_output_topology": "four row-aligned west-facing drivers",
                "maximum_welltap_pitch_um": MAX_TAP_PITCH,
                "minimum_functional_cell_gap_um": SITE,
                "no_u_turns": True,
                "no_orphan_vias": True,
                "boundary_ingress_pin_aligned": True,
            },
            "placements": placed,
            "well_taps": taps,
            "fillers": fillers,
            "counts": {
                "mapped_standard_cells": len(placed),
                "well_taps": len(taps),
                "fillers": len(fillers),
                "total_instances": len(placed) + len(taps) + len(fillers),
                "by_role": dict(sorted(role_counts.items())),
            },
            "metrics": {
                "placement_hpwl_um": self.hpwl(),
                "functional_area_um2": sum(
                    (item["bbox_um"][2] - item["bbox_um"][0])
                    * (item["bbox_um"][3] - item["bbox_um"][1])
                    for item in placed
                ),
                "region_area_um2": (X1 - X0) * ROW_COUNT * ROW,
                "orientation_optimization": orientation_audit,
            },
            "routing_intent": {
                "vector_outputs": "west-facing final drivers followed by a formally planned M2/M3 channel fanout",
                "phase_outputs": "one driver per phase-root row; equalization occurs before the existing balanced M4 trees",
                "configuration": "bit 31 entry and alternating-row serpentine chain without long return loops",
                "clock_reset": "pin-ordered compact top-entry bank with short branches to paired synchronizer and storage banks",
                "power": "continuous fill rows and explicit taps; upper-metal connection is a separate gate",
            },
        }
        x_values = [round(181.93 + 2.76 * index, 6) for index in range(14)]
        result["boundary_interface"] = {
            "edge": "north",
            "layer": "met2",
            "official_pin_order_left_to_right": OFFICIAL_PIN_ORDER,
            "local_pin_x_um": dict(zip(OFFICIAL_PIN_ORDER, x_values)),
            "local_pitch_um": 2.76,
            "track_pitch_um": 0.46,
            "policy": {
                "order_matches_fixed_tinytapeout_pins": True,
                "constant_pitch": True,
                "controller_bbox_preserved": True,
                "analog_geometry_unchanged": True,
            },
        }
        result["routing_intent"]["north_boundary"] = (
            "compact port bank in exact fixed-pin order; no top-level net permutation"
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping", type=Path, nargs="?",
        default=Path("build/v3/control_mapping/physical_mapping.json"),
    )
    parser.add_argument(
        "output", type=Path, nargs="?",
        default=Path("build/v3/control_placement/physical_control_placement.json"),
    )
    args = parser.parse_args()
    placement = V3ControllerPlacer(json.loads(args.mapping.read_text(encoding="utf-8"))).result()
    placement["provenance"] = {
        "mapping": str(args.mapping),
        "mapping_sha256": sha256(args.mapping),
        "generator": str(Path(__file__).relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(placement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **placement["counts"], **placement["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
