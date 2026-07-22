#!/usr/bin/env python3
"""Generate a deterministic connectivity-aware V2 standard-cell placement.

This is intentionally not a generic row packer.  The phase and trim banks use
explicit data-flow topologies; only the residual global combinational logic is
legalized from a connectivity relaxation.  Every coordinate is on the SKY130
HD site/row grid and every row receives explicit well taps.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from map_control_netlist import lef_cell_spec


SITE = 0.46
ROW = 2.72
POWER_PINS = {"VGND", "VPWR", "VPB", "VNB"}
INDEX_RE = re.compile(r"\[([0-9]+)\]$")


def snap_site(value: float) -> float:
    return round(value / SITE) * SITE


def row_orientation(row: int, horizontal_mirror: bool = False) -> str:
    if row % 2 == 0:
        return "MY" if horizontal_mirror else "R0"
    return "R180" if horizontal_mirror else "MX"


def bit_index(net: str) -> int:
    match = INDEX_RE.search(net)
    if not match:
        raise ValueError(f"net has no bit index: {net}")
    return int(match.group(1))


def access_center(spec: dict[str, Any], pin: str) -> tuple[float, float, str]:
    """Choose a stable uppermost LEF access point for placement estimation."""

    accesses = spec["pins"][pin]["access_rects"]
    rank = {"met2": 3, "met1": 2, "li1": 1}
    best_rank = max(rank.get(item["layer"], 0) for item in accesses)
    candidates = [item for item in accesses if rank.get(item["layer"], 0) == best_rank]
    width, height = map(float, spec["size_um"])

    def key(item: dict[str, Any]) -> tuple[float, float, float]:
        x0, y0, x1, y1 = map(float, item["rect_um"])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return ((cx - width / 2.0) ** 2 + (cy - height / 2.0) ** 2,
                -(x1 - x0) * (y1 - y0), cx)

    chosen = min(candidates, key=key)
    x0, y0, x1, y1 = map(float, chosen["rect_um"])
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, chosen["layer"]


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
    raise ValueError(f"unsupported standard-cell orientation {orientation}")


class Placer:
    def __init__(
        self,
        mapping: dict[str, Any],
        integration: dict[str, Any],
        floorplan: dict[str, Any],
        tap_spec: dict[str, Any],
    ) -> None:
        self.mapping = mapping
        self.integration = integration
        self.floorplan = floorplan
        self.library = dict(mapping["library"])
        self.library["tapvpwrvgnd"] = tap_spec
        self.cells = {cell["instance"]: cell for cell in mapping["cells"]}
        self.placements: dict[str, dict[str, Any]] = {}
        self.regions = {
            item["name"]: item for item in integration["placement_regions"]
        }
        self.row_cells: dict[tuple[str, int], list[str]] = defaultdict(list)
        self.orientation_audit: dict[str, Any] = {}

    def add(
        self,
        instance: str,
        x: float,
        row: int,
        orientation: str,
        rationale: str,
    ) -> None:
        if instance in self.placements:
            raise ValueError(f"duplicate placement for {instance}")
        cell = self.cells[instance]
        region = cell["region"]
        region_box = list(map(float, self.regions[region]["bbox"]))
        y = region_box[1] + row * ROW
        x = snap_site(x)
        width, height = map(float, cell["size_um"])
        if x < region_box[0] - 1e-9 or x + width > region_box[2] + 1e-9:
            raise ValueError(f"{instance} leaves {region} in X")
        if y < region_box[1] - 1e-9 or y + height > region_box[3] + 1e-9:
            raise ValueError(f"{instance} leaves {region} in Y")
        record = {
            "instance": instance,
            "cell": cell["cell"],
            "short_cell": cell["short_cell"],
            "role": cell["role"],
            "region": region,
            "row": row,
            "origin_um": [round(x, 6), round(y, 6)],
            "bbox_um": [round(x, 6), round(y, 6), round(x + width, 6), round(y + height, 6)],
            "orientation": orientation,
            "rationale": rationale,
        }
        self.placements[instance] = record
        self.row_cells[(region, row)].append(instance)

    def add_pair(
        self,
        prefix: str,
        x: float,
        row: int,
        output_left: bool,
        rationale: str,
    ) -> None:
        mux_name = f"{prefix}/enable_mux"
        ff_name = f"{prefix}/state_ff"
        mux = self.cells[mux_name]
        ff = self.cells[ff_name]
        if output_left:
            # The FF is physically left of its enable mux.  Mirror only the
            # FF so D faces right; an unmirrored mux keeps X facing left.
            self.add(ff_name, x, row, row_orientation(row, True), rationale)
            self.add(
                mux_name,
                x + float(ff["size_um"][0]) + SITE,
                row,
                row_orientation(row),
                rationale,
            )
        else:
            # The mux is physically left of the FF.  Mirror only the mux so
            # X faces right; an unmirrored FF keeps D facing left.
            self.add(mux_name, x, row, row_orientation(row, True), rationale)
            self.add(
                ff_name,
                x + float(mux["size_um"][0]) + SITE,
                row,
                row_orientation(row),
                rationale,
            )

    def pair_prefixes(self, region: str, role: str) -> dict[int, str]:
        result: dict[int, str] = {}
        unnamed: list[str] = []
        for cell in self.cells.values():
            if cell["region"] != region or cell["role"] != role:
                continue
            if not cell["instance"].endswith("/state_ff"):
                continue
            match = INDEX_RE.search(cell["pins"]["Q"])
            prefix = cell["instance"].rsplit("/", 1)[0]
            if match:
                result[int(match.group(1))] = prefix
            else:
                unnamed.append(prefix)
        missing = [index for index in range(len(result) + len(unnamed)) if index not in result]
        if len(missing) != len(unnamed):
            raise ValueError(f"cannot infer unnamed storage indices for {region}/{role}")
        for index, prefix in zip(missing, sorted(unnamed)):
            result[index] = prefix
        return result

    def place_phase(self) -> None:
        region = "phase_configuration_bank"
        handoffs = {
            (int(item["channel"]), item["signal"]): float(item["x"])
            for item in self.integration["phase_control_handoffs"]["routes"]
        }
        pin_specs = self.mapping["library"]
        for channel in range(4):
            cells = [
                cell for cell in self.cells.values()
                if cell["role"] == f"channel{channel}_phase_decode"
            ]
            drivers: list[tuple[float, dict[str, Any]]] = []
            predecessors: list[dict[str, Any]] = []
            targets = {
                f"phase_select0[{channel}]": handoffs[(channel, "phase_select0")],
                f"phase_select1[{channel}]": handoffs[(channel, "phase_select1")],
                f"phase_enable[{channel}]": handoffs[(channel, "phase_enable")],
            }
            for cell in cells:
                outputs = [
                    net for pin, net in cell["pins"].items()
                    if pin_specs[cell["short_cell"]]["pins"].get(pin, {}).get("direction") == "output"
                ]
                target = next((targets[net] for net in outputs if net in targets), None)
                (drivers if target is not None else predecessors).append(
                    (target, cell) if target is not None else cell
                )
            drivers.sort(key=lambda item: item[0])
            width = sum(float(cell["size_um"][0]) for _, cell in drivers)
            center = float(self.floorplan["channels"][3 - channel]["center_x"])
            # floorplan channels are stored 0..3, despite descending X.
            center = next(
                float(item["center_x"]) for item in self.floorplan["channels"]
                if int(item["index"]) == channel
            )
            x = snap_site(center - width / 2.0)
            site_offsets = {
                0: (0.0, 7 * SITE, 7 * SITE),
                2: (0.0, 2 * SITE, 2 * SITE),
            }.get(channel, (0.0, 0.0, 0.0))
            for driver_index, (_, cell) in enumerate(drivers):
                output_net = next(
                    net for pin, net in cell["pins"].items()
                    if pin_specs[cell["short_cell"]]["pins"].get(pin, {}).get("direction")
                    == "output"
                )
                mirror_toward_handoff = (
                    output_net == f"phase_select1[{channel}]" and channel in (1, 2, 3)
                )
                self.add(
                    cell["instance"], x + site_offsets[driver_index], 0,
                    row_orientation(0, mirror_toward_handoff),
                    f"CH{channel} final decode points toward and is site-spaced for its handoff",
                )
                x += float(cell["size_um"][0])
            predecessors.sort(key=lambda cell: cell["instance"])
            width = sum(float(cell["size_um"][0]) for cell in predecessors)
            x = snap_site(center - width / 2.0)
            for cell in predecessors:
                self.add(
                    cell["instance"], x, 1, row_orientation(1),
                    f"CH{channel} exclusive predecessor above its final decode",
                )
                x += float(cell["size_um"][0])

        active = self.pair_prefixes(region, "phase_active_storage")
        pair_width = 4.14 + SITE + 9.20
        for index, prefix in sorted(active.items()):
            channel, phase_bit = divmod(index, 2)
            center = next(
                float(item["center_x"]) for item in self.floorplan["channels"]
                if int(item["index"]) == channel
            )
            row = 2 + phase_bit
            self.add_pair(
                prefix,
                snap_site(center - pair_width / 2.0),
                row,
                output_left=phase_bit == 0,
                rationale=f"CH{channel} active phase bit {phase_bit} aligned over local decode",
            )

        shift = self.pair_prefixes(region, "phase_shift_storage")
        # Interleave the serial stages by channel directly above the active
        # phase registers that consume them.  The data flow is
        # cfg_data -> 7 -> ... -> 0, so consecutive stages alternate between
        # rows 5 and 4 while progressing monotonically from CH3 to CH0.  This
        # replaces the former two half-chain fold, whose shift_bits[7] trunk
        # spanned almost the entire phase bank, with seven short local row
        # transitions.
        #
        # Even stages are shifted sixteen sites toward the following odd-stage
        # column.  That puts their Q/A1 span around the next A0 access while
        # keeping the four pairs widely separated on the row.  All pairs keep
        # the mux on the left and FF on the right: mux X faces FF D, FF Q faces
        # the next stage, cfg_data enters at the left edge, and bit 0 exits on
        # the service-corridor side.
        even_row_offset = (
            int(self.integration["rules"]["phase_shift_even_row_offset_sites"])
            * SITE
        )
        for channel in range(4):
            center = next(
                float(item["center_x"]) for item in self.floorplan["channels"]
                if int(item["index"]) == channel
            )
            active_x = snap_site(center - pair_width / 2.0)
            even_index = 2 * channel
            odd_index = even_index + 1
            self.add_pair(
                shift[even_index], active_x + even_row_offset, 4, False,
                f"phase shift bit {even_index} interleaved above CH{channel}; "
                "Q faces the next odd-stage column",
            )
            self.add_pair(
                shift[odd_index], active_x, 5, False,
                f"phase shift bit {odd_index} aligned above CH{channel}; "
                "cfg/preceding-stage input enters from the left",
            )

    def place_trim(self) -> None:
        active = self.pair_prefixes("trim_configuration_bank", "trim_active_storage")
        shift = self.pair_prefixes("trim_configuration_bank", "trim_shift_storage")
        for index in range(16):
            # Keep the FF/mux order but mirror only the mux so Q faces its
            # feedback input and the shift-chain inputs stay on the service
            # side.  This deliberately spends 12 um on enabled_d: reversing
            # the pair makes enabled_d 2.3 um but increases total placement
            # HPWL by 74.423 um and weighted HPWL by 169.150.  The longer net
            # switches only during configuration and is therefore the safer
            # place to absorb this geometrically measured tradeoff.
            prefix = active[index]
            ff_name = f"{prefix}/state_ff"
            mux_name = f"{prefix}/enable_mux"
            ff = self.cells[ff_name]
            x = 184.92 + index * 3 * SITE
            rationale = (
                f"trim[{index}] inward-facing Q preserves the shorter total "
                "trim-bank topology; enabled_d is the static tradeoff net"
            )
            self.add(ff_name, x, index, row_orientation(index), rationale)
            self.add(
                mux_name,
                x + float(ff["size_um"][0]) + SITE,
                index,
                row_orientation(index, True),
                rationale,
            )
            self.add_pair(
                shift[index], 239.20, index, output_left=bool(index % 2),
                rationale="one-stage-per-row folded shift chain beside service corridor",
            )

    def q_cell(self, net: str) -> dict[str, Any]:
        matches = [
            cell for cell in self.cells.values()
            if cell["region"] == "global_control_core" and cell["pins"].get("Q") == net
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one global Q driver for {net}, found {len(matches)}")
        return matches[0]

    def place_global_fixed(self) -> None:
        # Two compact synchronizer bands.  The bit ordering follows the actual
        # TinyTapeout top-pin X order, so neither stage needs a crossover.
        for group, bits in enumerate(((4, 5, 6, 7), (0, 1, 2, 3))):
            meta_row = 8 + group
            sync_row = 6 + group
            x0 = 114.08 if group == 0 else 124.20
            for slot, index in enumerate(reversed(bits)):
                x = x0 + slot * 9.66
                meta = self.q_cell(f"direct_meta[{index}]")
                sync_net = (
                    f"direct_sync[{index}]" if index in (0, 3)
                    else f"beam_sync[{index - 1}]" if index in (1, 2)
                    else f"channel_enable_sync[{index - 4}]"
                )
                sync = self.q_cell(sync_net)
                self.add(
                    meta["instance"], x, meta_row, row_orientation(meta_row),
                    f"first synchronizer stage for top input bit {index}",
                )
                self.add(
                    sync["instance"], x, sync_row, row_orientation(sync_row),
                    f"second synchronizer stage vertically aligned to bit {index}",
                )

        pair_width = 13.80
        active_nets = [
            "active_channel_enable[3]", "active_channel_enable[2]",
            "active_channel_enable[1]", "active_channel_enable[0]",
        ]
        for net in active_nets:
            cell = self.q_cell(net)
            channel = bit_index(net)
            center = next(
                float(item["center_x"]) for item in self.floorplan["channels"]
                if int(item["index"]) == channel
            )
            self.add_pair(
                cell["instance"].rsplit("/", 1)[0],
                center - pair_width / 2.0,
                1,
                output_left=False,
                rationale=f"active channel-enable {channel} aligned over owning decode",
            )
        for slot, net in enumerate(("active_beam[0]", "active_manual", "active_beam[1]")):
            cell = self.q_cell(net)
            self.add_pair(
                cell["instance"].rsplit("/", 1)[0],
                101.20 + slot * 18.40,
                2,
                output_left=False,
                rationale=f"{net} placed beside the channel decode fanout",
            )

        blank = self.q_cell("blank_reg")
        self.add(
            blank["instance"], 167.44, 1, row_orientation(1),
            "blanking state beside phase-enable fanout",
        )

        quadrature = [
            cell for cell in self.cells.values() if cell["role"] == "quadrature_core"
        ]
        quadrature.sort(key=lambda cell: (cell["short_cell"] not in ("dfrtp", "dfstp"), cell["instance"]))
        total = sum(float(cell["size_um"][0]) for cell in quadrature) + SITE * (len(quadrature) - 1)
        x = snap_site(123.28 - total / 2.0)
        for cell in quadrature:
            self.add(
                cell["instance"], x, 0, row_orientation(0),
                "quadrature generator centered over four balanced phase roots",
            )
            x += float(cell["size_um"][0]) + SITE

        config_nets = (
            "cfg_commit_toggle", "cfg_toggle_meta", "cfg_toggle_sync",
            "cfg_toggle_seen", "cfg_pending",
        )
        rows = (4, 4, 4, 3, 3)
        cursor = {3: 197.80, 4: 197.80}
        for net, row in zip(config_nets, rows):
            cell = self.q_cell(net)
            if cell["instance"].endswith("/state_ff"):
                prefix = cell["instance"].rsplit("/", 1)[0]
                self.add_pair(
                    prefix, cursor[row], row, False,
                    f"{net} placed beside shielded configuration service corridor",
                )
                cursor[row] += 14.26
            else:
                self.add(
                    cell["instance"], cursor[row], row, row_orientation(row),
                    f"{net} synchronizer beside configuration service corridor",
                )
                cursor[row] += float(cell["size_um"][0]) + SITE

    def pin_anchors(self) -> dict[str, tuple[float, float]]:
        pins = self.floorplan["digital_reference_pins"]
        anchors = {
            "clk": tuple(map(float, pins["clk"])),
            "rst_n": tuple(map(float, pins["rst_n"])),
            "ena": tuple(map(float, pins["ena"])),
            "beam_select[0]": (138.46, 225.26),
            "beam_select[1]": (135.70, 225.26),
            "manual_mode": (130.18, 225.26),
            "channel_enable[0]": (127.42, 225.26),
            "channel_enable[1]": (124.66, 225.26),
            "channel_enable[2]": (121.90, 225.26),
            "channel_enable[3]": (119.14, 225.26),
            "cfg_clk": (116.38, 225.26),
            "cfg_data": (113.62, 225.26),
            "cfg_latch": (110.86, 225.26),
            "mixers_blank": (123.28, 176.0),
        }
        for root, net in zip(
            self.integration["quadrature_root_handoffs"],
            ("phase_wave[0]", "phase_wave[1]", "phase_wave[3]", "phase_wave[2]"),
        ):
            anchors[net] = tuple(map(float, root["point"]))
        for item in self.integration["phase_control_handoffs"]["routes"]:
            anchors[f"{item['signal']}[{item['channel']}]"] = (
                float(item["x"]), float(self.integration["phase_control_handoffs"]["transition_y"])
            )
        trim = self.integration["trim_control_bus"]
        for index in range(16):
            anchors[f"active_trim_codes[{index}]"] = (
                float(trim["source_region_x"]),
                float(trim["first_track_y"]) + index * float(trim["track_pitch"]),
            )
        return anchors

    def cell_center(self, instance: str) -> tuple[float, float]:
        box = self.placements[instance]["bbox_um"]
        return (float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0

    def pin_point(
        self, instance: str, pin: str, orientation: str | None = None
    ) -> tuple[float, float]:
        cell = self.cells[instance]
        placement = self.placements[instance]
        spec = self.library[cell["short_cell"]]
        local_x, local_y, _ = access_center(spec, pin)
        width, height = map(float, spec["size_um"])
        transformed = transform_point(
            (local_x, local_y), width, height,
            orientation or placement["orientation"],
        )
        return (
            float(placement["origin_um"][0]) + transformed[0],
            float(placement["origin_um"][1]) + transformed[1],
        )

    def orient_global_residual(self) -> None:
        """Point residual logic pins toward their real neighbors.

        Every vendored HD LEF declares X/Y symmetry.  Therefore R0<->MY and
        MX<->R180 are legal in-row alternatives with identical cell bboxes and
        supply abutment.  Only the connectivity-relaxed residual logic is
        eligible; structured shift chains, synchronizers, and matched decode
        pairs retain their explicitly planned orientations.
        """

        candidates = sorted(
            item["instance"] for item in self.placements.values()
            if item["rationale"]
            == "connectivity-relaxed global logic legalized on the nearest open site"
        )
        mirror = {"R0": "MY", "MY": "R0", "MX": "R180", "R180": "MX"}
        anchors = self.pin_anchors()

        def cell_score(instance: str, orientation: str) -> float:
            cell = self.cells[instance]
            score = 0.0
            for pin, net in cell["pins"].items():
                if pin in POWER_PINS:
                    continue
                peers: list[tuple[float, float]] = []
                for endpoint in self.mapping["nets"].get(net, []):
                    other = endpoint["instance"]
                    if other == instance or other not in self.placements:
                        continue
                    peers.append(self.pin_point(other, endpoint["pin"]))
                if net in anchors:
                    peers.append(anchors[net])
                if not peers:
                    continue
                target_x = statistics.median(point[0] for point in peers)
                target_y = statistics.median(point[1] for point in peers)
                point_x, point_y = self.pin_point(instance, pin, orientation)
                score += (
                    abs(point_x - target_x) + abs(point_y - target_y)
                ) / len(peers)
            return score

        initial_orientations = {
            name: self.placements[name]["orientation"] for name in candidates
        }
        initial_score = sum(
            cell_score(name, self.placements[name]["orientation"])
            for name in candidates
        )
        changed: set[str] = set()
        for _ in range(4):
            pass_changed = False
            for name in candidates:
                current = self.placements[name]["orientation"]
                alternative = mirror[current]
                if cell_score(name, alternative) + 0.05 < cell_score(name, current):
                    self.placements[name]["orientation"] = alternative
                    changed.add(name)
                    pass_changed = True
            if not pass_changed:
                break
        final_score = sum(
            cell_score(name, self.placements[name]["orientation"])
            for name in candidates
        )
        for name in changed:
            self.placements[name]["rationale"] += (
                "; legal horizontal mirror minimizes actual pin-to-neighbor demand"
            )
        self.orientation_audit = {
            "eligible_residual_cells": len(candidates),
            "changed_cell_count": sum(
                self.placements[name]["orientation"] != initial_orientations[name]
                for name in candidates
            ),
            "initial_pin_demand_um": initial_score,
            "final_pin_demand_um": final_score,
            "improvement_um": initial_score - final_score,
            "improvement_fraction": 1.0 - final_score / initial_score,
            "legal_transform_pairs": ["R0<->MY", "MX<->R180"],
        }

    def place_global_residual(self) -> None:
        remaining = [
            cell for cell in self.cells.values()
            if cell["region"] == "global_control_core" and cell["instance"] not in self.placements
        ]
        remaining_names = {cell["instance"] for cell in remaining}
        positions: dict[str, tuple[float, float]] = {
            name: self.cell_center(name) for name in self.placements
        }
        anchors = self.pin_anchors()
        for cell in remaining:
            positions[cell["instance"]] = (167.21, 209.44)

        # Relax against placed neighbours and real boundary anchors.  Fanout is
        # normalized per net so clock/reset do not collapse the whole core.
        for _ in range(120):
            updated: dict[str, tuple[float, float]] = {}
            for cell in remaining:
                samples: list[tuple[float, float, float]] = []
                for pin, net in cell["pins"].items():
                    if pin in POWER_PINS:
                        continue
                    endpoints = self.mapping["nets"].get(net, [])
                    net_weight = 1.0 / max(1, len(endpoints) - 1)
                    if net in anchors:
                        samples.append((*anchors[net], 2.5 * net_weight))
                    for endpoint in endpoints:
                        other = endpoint["instance"]
                        if other == cell["instance"] or other not in positions:
                            continue
                        samples.append((*positions[other], net_weight))
                if not samples:
                    samples.append((167.21, 209.44, 1.0))
                # A weak seed keeps service-related anonymous logic on the
                # right without overpowering actual connectivity.
                if any(net in {"cfg_clk", "cfg_latch", "apply_config"}
                       for net in cell["pins"].values()):
                    samples.append((238.0, 209.44, 0.5))
                weight = sum(item[2] for item in samples)
                updated[cell["instance"]] = (
                    sum(item[0] * item[2] for item in samples) / weight,
                    sum(item[1] * item[2] for item in samples) / weight,
                )
            positions.update(updated)

        region = self.regions["global_control_core"]
        x0, y0, x1, _ = map(float, region["bbox"])
        row_limit = 0.55 * (x1 - x0)
        used = {row: sum(
            float(self.cells[name]["size_um"][0])
            for name in self.row_cells.get(("global_control_core", row), [])
        ) for row in range(10)}
        assigned: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for cell in sorted(remaining, key=lambda item: (positions[item["instance"]][1], item["instance"])):
            preferred = min(5, max(0, round((positions[cell["instance"]][1] - y0) / ROW)))
            choices = sorted(range(6), key=lambda row: (abs(row - preferred), used[row], row))
            width = float(cell["size_um"][0])
            row = next(row for row in choices if used[row] + width <= row_limit + 1e-9)
            assigned[row].append(cell)
            used[row] += width

        for row, cells in assigned.items():
            occupied = [
                tuple(map(float, self.placements[name]["bbox_um"]))
                for name in self.row_cells.get(("global_control_core", row), [])
            ]
            for cell in sorted(cells, key=lambda item: (positions[item["instance"]][0], item["instance"])):
                width = float(cell["size_um"][0])
                target = positions[cell["instance"]][0] - width / 2.0
                candidates: list[tuple[float, float]] = []
                first_site = math.ceil(x0 / SITE - 1e-9)
                last_site = math.floor((x1 - width) / SITE + 1e-9)
                for site in range(first_site, last_site + 1):
                    x = site * SITE
                    if any(
                        x < box[2] + SITE - 1e-9
                        and x + width > box[0] - SITE + 1e-9
                        for box in occupied
                    ):
                        continue
                    candidates.append((abs(x - target), x))
                if not candidates:
                    raise ValueError(f"cannot legalize {cell['instance']} in global row {row}")
                x = min(candidates)[1]
                self.add(
                    cell["instance"], x, row, row_orientation(row),
                    "connectivity-relaxed global logic legalized on the nearest open site",
                )
                occupied.append((x, y0 + row * ROW, x + width, y0 + (row + 1) * ROW))

    def add_taps(self) -> None:
        max_pitch = float(self.integration["rules"]["maximum_welltap_pitch"])
        for region_name in (
            "phase_configuration_bank", "global_control_core", "trim_configuration_bank"
        ):
            region = self.regions[region_name]
            x0, y0, x1, _ = map(float, region["bbox"])
            row_count = int(region["row_count"])
            for row in range(row_count):
                occupied = [
                    tuple(map(float, self.placements[name]["bbox_um"]))
                    for name in self.row_cells.get((region_name, row), [])
                ]
                candidates: list[float] = []
                for site in range(math.ceil(x0 / SITE - 1e-9), math.floor((x1 - SITE) / SITE + 1e-9) + 1):
                    x = site * SITE
                    if not any(x < box[2] - 1e-9 and x + SITE > box[0] + 1e-9 for box in occupied):
                        candidates.append(x)
                taps: list[float] = []
                cursor = x0
                while x1 - cursor > max_pitch + 1e-9:
                    possible = [x for x in candidates if cursor - 1e-9 <= x <= cursor + max_pitch + 1e-9]
                    if not possible:
                        raise ValueError(f"no well-tap site in {region_name} row {row} after {cursor}")
                    chosen = max(possible)
                    if taps and chosen <= taps[-1] + 1e-9:
                        raise ValueError(f"well-tap insertion stalled in {region_name} row {row}")
                    taps.append(chosen)
                    candidates = [x for x in candidates if x > chosen + 1e-9]
                    cursor = chosen
                if not taps:
                    taps.append(min(candidates, key=lambda x: abs(x - (x0 + x1) / 2.0)))
                elif x1 - taps[-1] > max_pitch + 1e-9:
                    taps.append(max(candidates))
                for index, x in enumerate(taps):
                    name = f"TAP_{region_name}_R{row:02d}_{index:02d}"
                    orientation = row_orientation(row)
                    self.placements[name] = {
                        "instance": name,
                        "cell": "sky130_fd_sc_hd__tapvpwrvgnd_1",
                        "short_cell": "tapvpwrvgnd",
                        "role": "well_tap",
                        "region": region_name,
                        "row": row,
                        "origin_um": [round(x, 6), round(y0 + row * ROW, 6)],
                        "bbox_um": [round(x, 6), round(y0 + row * ROW, 6),
                                    round(x + SITE, 6), round(y0 + (row + 1) * ROW, 6)],
                        "orientation": orientation,
                        "rationale": "explicit well/substrate tap within frozen maximum pitch",
                    }
                    self.row_cells[(region_name, row)].append(name)

    def add_fillers(self) -> None:
        """Fill every remaining row site to preserve continuous well/rail geometry.

        A top-level M1 rail can feed VPWR while an isolated standard-cell n-well
        still leaves VPB floating.  The foundry fill_1 macro closes every legal
        one-site gap with qualified well, implant, LI, and M1 geometry.
        """

        for region_name, region in self.regions.items():
            if "row_count" not in region:
                continue
            x0, y0, x1, _ = map(float, region["bbox"])
            for row in range(int(region["row_count"])):
                occupied = [
                    list(map(float, self.placements[name]["bbox_um"]))
                    for name in self.row_cells.get((region_name, row), [])
                ]
                first_site = math.ceil(x0 / SITE - 1e-9)
                last_site = math.floor((x1 - SITE) / SITE + 1e-9)
                fill_index = 0
                for site in range(first_site, last_site + 1):
                    x = site * SITE
                    if any(
                        x < box[2] - 1e-9 and x + SITE > box[0] + 1e-9
                        for box in occupied
                    ):
                        continue
                    name = f"FILL_{region_name}_R{row:02d}_{fill_index:04d}"
                    orientation = row_orientation(row)
                    self.placements[name] = {
                        "instance": name,
                        "cell": "sky130_fd_sc_hd__fill_1",
                        "short_cell": "fill",
                        "role": "power_filler",
                        "region": region_name,
                        "row": row,
                        "origin_um": [round(x, 6), round(y0 + row * ROW, 6)],
                        "bbox_um": [round(x, 6), round(y0 + row * ROW, 6),
                                    round(x + SITE, 6), round(y0 + (row + 1) * ROW, 6)],
                        "orientation": orientation,
                        "rationale": "foundry filler closes row well and supply-rail continuity",
                    }
                    self.row_cells[(region_name, row)].append(name)
                    occupied.append(self.placements[name]["bbox_um"])
                    fill_index += 1

    def attach_pin_access(self) -> None:
        for name, placement in self.placements.items():
            if placement["role"] in ("well_tap", "power_filler"):
                continue
            cell = self.cells[name]
            spec = self.library[cell["short_cell"]]
            x, y = map(float, placement["origin_um"])
            width, height = map(float, spec["size_um"])
            accesses: dict[str, dict[str, Any]] = {}
            for pin in cell["pins"]:
                if pin in POWER_PINS:
                    continue
                px, py, layer = access_center(spec, pin)
                px, py = transform_point((px, py), width, height, placement["orientation"])
                accesses[pin] = {"net": cell["pins"][pin], "layer": layer,
                                 "point_um": [round(x + px, 6), round(y + py, 6)]}
            placement["pin_access"] = accesses

    def result(self) -> dict[str, Any]:
        self.place_phase()
        self.place_trim()
        self.place_global_fixed()
        self.place_global_residual()
        missing = set(self.cells) - set(self.placements)
        if missing:
            raise ValueError(f"unplaced mapped cells: {sorted(missing)}")
        self.orient_global_residual()
        self.add_taps()
        self.add_fillers()
        self.attach_pin_access()
        signal = [
            item for item in self.placements.values()
            if item["role"] not in ("well_tap", "power_filler")
        ]
        taps = [item for item in self.placements.values() if item["role"] == "well_tap"]
        fillers = [item for item in self.placements.values() if item["role"] == "power_filler"]
        return {
            "schema_version": 1,
            "units": "um",
            "status": "pre-route production placement candidate",
            "policy": {
                "site_width": SITE,
                "row_height": ROW,
                "row_orientations": "R0/MX with MY/R180 only for intentional horizontal pin reversal",
                "maximum_welltap_pitch_um": self.integration["rules"]["maximum_welltap_pitch"],
                "no_u_turns": True,
                "no_orphan_vias": True,
                "placement_method": "explicit phase/trim data flow plus connectivity-relaxed global legalization",
                "residual_orientation_method": "actual-pin median-neighbor cost over legal horizontal row mirrors",
            },
            "regions": {
                name: {"bbox": item["bbox"], "row_count": item.get("row_count")}
                for name, item in self.regions.items() if "row_count" in item
            },
            "placements": sorted(signal, key=lambda item: (item["region"], item["row"], item["origin_um"][0])),
            "well_taps": sorted(taps, key=lambda item: (item["region"], item["row"], item["origin_um"][0])),
            "fillers": sorted(fillers, key=lambda item: (item["region"], item["row"], item["origin_um"][0])),
            "counts": {
                "mapped_standard_cells": len(signal),
                "well_taps": len(taps),
                "fillers": len(fillers),
                "total_instances": len(signal) + len(taps) + len(fillers),
            },
            "orientation_optimization": self.orientation_audit,
            "routing_intent": {
                "phase_decode": "final drivers in handoff order; no channel output crosses another channel",
                "phase_shift": "channel-aligned two-row interleave; seven short local row transitions replace long regional shift-bit trunks",
                "trim_shift": "one stage per row with alternating left/right access and only adjacent-row transitions",
                "trim_outputs": "sixteen measured FF-left/mux-right pairs minimizing total trim-bank HPWL; only static enabled_d absorbs the local span",
                "clock_reset": "top entry plus straight service-corridor continuation; local horizontal row branches",
                "power": "continuous fill_1 well/rail rows, alternating M1 rails, explicit taps, redundant upper-metal contacts added before signals",
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("integration", type=Path)
    parser.add_argument("floorplan", type=Path)
    parser.add_argument("cell_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    placer = Placer(
        json.loads(args.mapping.read_text(encoding="utf-8")),
        json.loads(args.integration.read_text(encoding="utf-8")),
        json.loads(args.floorplan.read_text(encoding="utf-8")),
        lef_cell_spec(args.cell_dir / "sky130_fd_sc_hd__tapvpwrvgnd_1.lef"),
    )
    result = placer.result()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{args.output}: {result['counts']['mapped_standard_cells']} mapped cells, "
        f"{result['counts']['well_taps']} explicit well taps"
    )


if __name__ == "__main__":
    main()
