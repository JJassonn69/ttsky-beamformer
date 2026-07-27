#!/usr/bin/env python3
"""Map hierarchical Yosys generic cells to a minimal physical SKY130 set."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SIZE_RE = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;")
PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
DIRECTION_RE = re.compile(r"^\s*DIRECTION\s+(INPUT|OUTPUT|INOUT)\s*;")
LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;")
RECT_RE = re.compile(
    r"^\s*RECT\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+"
    r"(-?[0-9.]+)\s+(-?[0-9.]+)\s*;"
)

COMBINATIONAL_MAP = {
    "$_NOT_": ("inv", {"A": "A", "Y": "Y"}),
    "$_AND_": ("and2", {"A": "A", "B": "B", "Y": "X"}),
    "$_NAND_": ("nand2", {"A": "A", "B": "B", "Y": "Y"}),
    "$_NOR_": ("nor2", {"A": "A", "B": "B", "Y": "Y"}),
    "$_OR_": ("or2", {"A": "A", "B": "B", "Y": "X"}),
    "$_XOR_": ("xor2", {"A": "A", "B": "B", "Y": "X"}),
    # and2b computes !A_N & B, while the Yosys primitive is A & !B.
    "$_ANDNOT_": ("and2b", {"A": "B", "B": "A_N", "Y": "X"}),
    # or2b computes A | !B_N, identical to the Yosys ORNOT primitive.
    "$_ORNOT_": ("or2b", {"A": "A", "B": "B_N", "Y": "X"}),
    "$_MUX_": ("mux2", {"A": "A0", "B": "A1", "S": "S", "Y": "X"}),
}
DFF_RE = re.compile(r"^\$_DFF_PN([01])_$")
DFFE_RE = re.compile(r"^\$_DFFE_PN([01])([NP])_$")


def cell_region(path: str) -> str:
    if path.startswith("phase_config/"):
        return "phase_configuration_bank"
    if path.startswith("trim_config/"):
        return "trim_configuration_bank"
    return "global_control_core"


def cell_role(path: str, q_net: str | None = None) -> str:
    if "phase_config/" in path:
        if q_net and "/active_bits[" in q_net:
            return "phase_active_storage"
        if q_net and "/shift_bits[" in q_net:
            return "phase_shift_storage"
        return "phase_storage_logic"
    if "trim_config/" in path:
        if q_net and "/active_bits[" in q_net:
            return "trim_active_storage"
        if q_net and "/shift_bits[" in q_net:
            return "trim_shift_storage"
        return "trim_storage_logic"
    if path.startswith("quadrature_generator/"):
        return "quadrature_core"
    return "global_control_logic"


def sequential_role(
    module: dict[str, Any], path: str, generic: dict[str, Any]
) -> str:
    """Classify storage from its local named Q bit before hierarchy binding."""

    q_bits = generic.get("connections", {}).get("Q", [])
    if len(q_bits) == 1 and isinstance(q_bits[0], int):
        q_bit = q_bits[0]
        for net_name, net in module.get("netnames", {}).items():
            if q_bit not in net.get("bits", []):
                continue
            if net_name == "active_bits":
                return cell_role(path, f"{path}/active_bits[0]")
            if net_name == "shift_bits":
                return cell_role(path, f"{path}/shift_bits[0]")
    return cell_role(path)


def lef_cell_spec(path: Path) -> dict[str, Any]:
    size: list[float] | None = None
    pins: dict[str, dict[str, Any]] = {}
    current: str | None = None
    current_layer: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := SIZE_RE.match(line):
            size = [float(match.group(1)), float(match.group(2))]
        elif match := PIN_RE.match(line):
            current = match.group(1)
            current_layer = None
            pins[current] = {"access_rects": []}
        elif current is not None and (match := DIRECTION_RE.match(line)):
            pins[current]["direction"] = match.group(1).lower()
        elif current is not None and (match := LAYER_RE.match(line)):
            current_layer = match.group(1)
        elif current is not None and current_layer and (match := RECT_RE.match(line)):
            pins[current]["access_rects"].append({
                "layer": current_layer,
                "rect_um": [float(value) for value in match.groups()],
            })
        elif current is not None and line.strip() == f"END {current}":
            current = None
            current_layer = None
    if size is None:
        raise ValueError(f"{path}: missing SIZE")
    for pin, spec in pins.items():
        if "direction" not in spec:
            raise ValueError(f"{path}: pin {pin} has no DIRECTION")
        if not spec["access_rects"]:
            raise ValueError(f"{path}: pin {pin} has no access rectangles")
    return {"lef": str(path), "size_um": size, "pins": pins}


def library_specs(cell_dir: Path) -> dict[str, dict[str, Any]]:
    cells = {
        "inv", "and2", "mux2", "and2b", "dfrtp", "dfstp",
        "nand2", "nor2", "or2", "or2b", "xor2",
    }
    return {
        cell: lef_cell_spec(cell_dir / f"sky130_fd_sc_hd__{cell}_1.lef")
        for cell in sorted(cells)
    }


def partition_phase_decode(
    physical: list[dict[str, Any]], specs: dict[str, dict[str, Any]]
) -> None:
    """Move only channel-local output cones next to their selector handoffs.

    The final selector/control outputs otherwise originate in the global core
    and would cross the phase-storage bank.  A driver and an immediately
    preceding exclusive combinational cell are safe to localize; shared logic
    and every sequential element remain in their original region.
    """

    drivers: dict[str, dict[str, Any]] = {}
    sinks: dict[str, list[dict[str, Any]]] = {}
    for cell in physical:
        pin_specs = specs[cell["short_cell"]]["pins"]
        for pin, net in cell["pins"].items():
            direction = pin_specs.get(pin, {}).get("direction")
            if direction == "output":
                if net in drivers:
                    raise ValueError(f"multiple mapped drivers for {net}")
                drivers[net] = cell
            elif direction == "input":
                sinks.setdefault(net, []).append(cell)

    for channel in range(4):
        targets = (
            f"phase_select0[{channel}]",
            f"phase_select1[{channel}]",
            f"phase_enable[{channel}]",
        )
        local: dict[str, dict[str, Any]] = {}
        for target in targets:
            driver = drivers.get(target)
            if driver is None:
                raise ValueError(f"missing mapped driver for {target}")
            local[driver["instance"]] = driver
            pin_specs = specs[driver["short_cell"]]["pins"]
            for pin, net in driver["pins"].items():
                if pin_specs.get(pin, {}).get("direction") != "input":
                    continue
                predecessor = drivers.get(net)
                if predecessor is None or predecessor["short_cell"] in ("dfrtp", "dfstp"):
                    continue
                if len(sinks.get(net, [])) == 1:
                    local[predecessor["instance"]] = predecessor
        for cell in local.values():
            cell["region"] = "phase_configuration_bank"
            cell["role"] = f"channel{channel}_phase_decode"
def preferred_bit_names(module: dict[str, Any]) -> dict[int, str]:
    names: dict[int, str] = {}
    for port_name, port in module.get("ports", {}).items():
        bits = port["bits"]
        for index, bit in enumerate(bits):
            if isinstance(bit, int):
                names.setdefault(bit, port_name if len(bits) == 1 else f"{port_name}[{index}]")
    for net_name, net in module.get("netnames", {}).items():
        if net.get("hide_name"):
            continue
        bits = net["bits"]
        for index, bit in enumerate(bits):
            if isinstance(bit, int):
                names.setdefault(bit, net_name if len(bits) == 1 else f"{net_name}[{index}]")
    return names


def map_netlist(source: dict[str, Any], top: str, cell_dir: Path) -> dict[str, Any]:
    modules = source["modules"]
    if top not in modules:
        raise ValueError(f"missing top module {top}")
    specs = library_specs(cell_dir)
    physical: list[dict[str, Any]] = []
    top_ports: dict[str, dict[str, Any]] = {}
    port_aliases: dict[str, str] = {}
    net_parents: dict[str, str] = {}
    port_rank: dict[str, int] = {}

    def find_net(net: str) -> str:
        net_parents.setdefault(net, net)
        if net_parents[net] != net:
            net_parents[net] = find_net(net_parents[net])
        return net_parents[net]

    def union_nets(first: str, second: str) -> None:
        first_root = find_net(first)
        second_root = find_net(second)
        if first_root == second_root:
            return
        first_key = (port_rank.get(first_root, 1_000_000), first_root)
        second_key = (port_rank.get(second_root, 1_000_000), second_root)
        if second_key < first_key:
            first_root, second_root = second_root, first_root
        net_parents[second_root] = first_root

    def add_physical(
        instance: str,
        cell: str,
        pins: dict[str, str],
        source_type: str,
        role: str,
    ) -> None:
        expected = set(specs[cell]["pins"])
        signal_pins = expected - {"VGND", "VPWR", "VPB", "VNB"}
        if set(pins) != signal_pins:
            raise ValueError(
                f"{instance}: {cell} pin mismatch {sorted(pins)} != {sorted(signal_pins)}"
            )
        physical.append({
            "instance": instance,
            "cell": f"sky130_fd_sc_hd__{cell}_1",
            "short_cell": cell,
            "region": cell_region(instance),
            "role": role,
            "source_type": source_type,
            "pins": {**pins, "VGND": "VGND", "VPWR": "VDPWR"},
            "size_um": specs[cell]["size_um"],
        })

    def instantiate(
        module_name: str,
        path: str,
        bindings: dict[int, str] | None,
    ) -> None:
        module = modules[module_name]
        preferred = preferred_bit_names(module)
        local: dict[int, str] = dict(bindings or {})

        if bindings is None:
            rank = 0
            for port_name, port in module["ports"].items():
                bits = port["bits"]
                named: list[str] = []
                for index, bit in enumerate(bits):
                    net = port_name if len(bits) == 1 else f"{port_name}[{index}]"
                    port_rank[net] = rank
                    rank += 1
                    named.append(net)
                    if isinstance(bit, int):
                        # A Yosys bit can be exposed under more than one port
                        # name (active_phase_codes aliases phase_select0/1).
                        # Keep the first physical name and record later names
                        # as explicit aliases instead of silently overriding it.
                        if bit in local:
                            union_nets(local[bit], net)
                        else:
                            local[bit] = net
                top_ports[port_name] = {"direction": port["direction"], "nets": named}
            for port_name, port in module["ports"].items():
                for index, bit in enumerate(port["bits"]):
                    name = port_name if len(port["bits"]) == 1 else f"{port_name}[{index}]"
                    if isinstance(bit, int):
                        port_aliases[name] = find_net(local[bit])
                    elif bit == "0":
                        port_aliases[name] = "VGND"
                    elif bit == "1":
                        port_aliases[name] = "VDPWR"

        def net_for(bit: int | str) -> str:
            if bit == "0":
                return "VGND"
            if bit == "1":
                return "VDPWR"
            if not isinstance(bit, int):
                raise ValueError(f"unsupported constant {bit!r}")
            if bit not in local:
                name = preferred.get(bit, f"net_{bit}")
                local[bit] = f"{path}/{name}" if path else name
            return local[bit]

        for original_name, generic in module.get("cells", {}).items():
            generic_type = generic["type"]
            instance = f"{path}/{original_name}" if path else f"core/{original_name}"
            connections = {
                pin: [net_for(bit) for bit in bits]
                for pin, bits in generic["connections"].items()
            }
            if generic_type in modules:
                child = modules[generic_type]
                child_bindings: dict[int, str] = {}
                for port_name, port in child["ports"].items():
                    parent_nets = connections[port_name]
                    if len(parent_nets) != len(port["bits"]):
                        raise ValueError(f"{instance}.{port_name}: width mismatch")
                    for bit, net in zip(port["bits"], parent_nets):
                        if isinstance(bit, int):
                            if bit in child_bindings:
                                union_nets(child_bindings[bit], net)
                            else:
                                child_bindings[bit] = net
                instantiate(generic_type, f"{path}/{original_name}".strip("/"), child_bindings)
                continue
            if generic_type in COMBINATIONAL_MAP:
                short_cell, pin_map = COMBINATIONAL_MAP[generic_type]
                pins = {
                    physical_pin: connections[generic_pin][0]
                    for generic_pin, physical_pin in pin_map.items()
                }
                add_physical(
                    instance, short_cell, pins, generic_type, cell_role(instance)
                )
                continue
            if generic_type == "$_XNOR_":
                # The deliberately small vendored physical library includes
                # xor2_1 and inv_1 but not xnor2_1.  Preserve the exact generic
                # function as a two-cell cone instead of introducing an
                # untracked library dependency.
                xor_net = f"{instance}/xor"
                add_physical(
                    f"{instance}/xor2",
                    "xor2",
                    {
                        "A": connections["A"][0],
                        "B": connections["B"][0],
                        "X": xor_net,
                    },
                    generic_type,
                    cell_role(instance),
                )
                add_physical(
                    f"{instance}/inv",
                    "inv",
                    {"A": xor_net, "Y": connections["Y"][0]},
                    generic_type,
                    cell_role(instance),
                )
                continue
            if match := DFF_RE.match(generic_type):
                reset_value = match.group(1)
                short_cell = "dfrtp" if reset_value == "0" else "dfstp"
                reset_pin = "RESET_B" if reset_value == "0" else "SET_B"
                q_net = connections["Q"][0]
                add_physical(
                    instance,
                    short_cell,
                    {
                        "D": connections["D"][0],
                        "Q": q_net,
                        reset_pin: connections["R"][0],
                        "CLK": connections["C"][0],
                    },
                    generic_type,
                    sequential_role(module, instance, generic),
                )
                continue
            if match := DFFE_RE.match(generic_type):
                reset_value, enable_polarity = match.groups()
                q_net = connections["Q"][0]
                d_net = connections["D"][0]
                e_net = connections["E"][0]
                mux_net = f"{instance}/enabled_d"
                if enable_polarity == "P":
                    a0, a1 = q_net, d_net
                else:
                    a0, a1 = d_net, q_net
                add_physical(
                    f"{instance}/enable_mux",
                    "mux2",
                    {"A0": a0, "A1": a1, "S": e_net, "X": mux_net},
                    generic_type,
                    cell_role(instance),
                )
                short_cell = "dfrtp" if reset_value == "0" else "dfstp"
                reset_pin = "RESET_B" if reset_value == "0" else "SET_B"
                add_physical(
                    f"{instance}/state_ff",
                    short_cell,
                    {
                        "D": mux_net,
                        "Q": q_net,
                        reset_pin: connections["R"][0],
                        "CLK": connections["C"][0],
                    },
                    generic_type,
                    sequential_role(module, instance, generic),
                )
                continue
            raise ValueError(f"{instance}: unsupported generic cell {generic_type}")

    instantiate(top, "", None)
    for cell in physical:
        cell["pins"] = {
            pin: find_net(net) for pin, net in cell["pins"].items()
        }
    port_aliases = {
        alias: find_net(canonical) for alias, canonical in port_aliases.items()
    }
    partition_phase_decode(physical, specs)
    instance_names = [cell["instance"] for cell in physical]
    if len(instance_names) != len(set(instance_names)):
        raise ValueError("mapped instance names are not unique")
    nets: dict[str, list[dict[str, str]]] = {}
    for cell in physical:
        for pin, net in cell["pins"].items():
            if pin in ("VGND", "VPWR"):
                continue
            nets.setdefault(net, []).append({"instance": cell["instance"], "pin": pin})
    return {
        "schema_version": 1,
        "top": top,
        "source_creator": source.get("creator"),
        "mapping_policy": {
            "library": "sky130_fd_sc_hd",
            "drive_strength": 1,
            "enabled_flop_implementation": "mux2_1 plus dfrtp_1/dfstp_1",
            "clock_polarity": "positive edge",
            "asynchronous_control_polarity": "active low",
        },
        "ports": top_ports,
        "port_aliases": port_aliases,
        "library": specs,
        "cells": physical,
        "nets": nets,
        "counts": {
            "total_cells": len(physical),
            "by_cell": dict(sorted(Counter(cell["short_cell"] for cell in physical).items())),
            "by_region": dict(sorted(Counter(cell["region"] for cell in physical).items())),
            "by_role": dict(sorted(Counter(cell["role"] for cell in physical).items())),
            "signal_nets": len(nets),
        },
    }


def verilog_identifier(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_$]", "_", name)


def render_structural_verilog(report: dict[str, Any]) -> str:
    """Render a simulation/checking view of the mapped physical cell graph."""

    ports = report["ports"]
    lines = [
        "// Generated by v2/tools/map_control_netlist.py; do not edit.",
        "`default_nettype none",
        "module v2_physical_control_core_mapped (",
        "    " + ",\n    ".join(ports) + "\n);",
    ]
    for name, port in ports.items():
        width = len(port["nets"])
        vector = f" [{width - 1}:0]" if width > 1 else ""
        lines.append(f"    {port['direction']} wire{vector} {name};")
    lines.extend(("    supply0 VGND;", "    supply1 VDPWR;"))

    expressions = {
        alias: alias for port in ports.values() for alias in port["nets"]
    }
    internal = sorted(
        net
        for net in report["nets"]
        if net not in expressions and net not in ("VGND", "VDPWR")
    )
    internal_names = {net: f"mapped_net_{index}" for index, net in enumerate(internal)}
    if internal_names:
        lines.append("    wire " + ", ".join(internal_names.values()) + ";")

    def expression(net: str) -> str:
        if net in ("VGND", "VDPWR"):
            return net
        if net in expressions:
            return expressions[net]
        return internal_names[net]

    for alias, canonical in sorted(report["port_aliases"].items()):
        if alias != canonical and ports[alias.split("[", 1)[0]]["direction"] == "output":
            lines.append(f"    assign {alias} = {expression(canonical)};")

    for index, cell in enumerate(report["cells"]):
        instance = verilog_identifier(cell["instance"])
        connections = ", ".join(
            f".{pin}({expression(net)})" for pin, net in cell["pins"].items()
        )
        lines.append(f"    {cell['cell']} {instance}_{index} ({connections});")
    lines.extend(("endmodule", "`default_nettype wire", ""))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generic_json", type=Path)
    parser.add_argument("cell_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--top", default="v2_physical_control_core")
    parser.add_argument("--verilog", type=Path)
    args = parser.parse_args()
    report = map_netlist(
        json.loads(args.generic_json.read_text(encoding="utf-8")),
        args.top,
        args.cell_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.verilog:
        args.verilog.parent.mkdir(parents=True, exist_ok=True)
        args.verilog.write_text(render_structural_verilog(report), encoding="utf-8")
    print(
        f"{args.output}: {report['counts']['total_cells']} physical cells, "
        f"{report['counts']['signal_nets']} signal nets, "
        f"regions={report['counts']['by_region']}"
    )


if __name__ == "__main__":
    main()
