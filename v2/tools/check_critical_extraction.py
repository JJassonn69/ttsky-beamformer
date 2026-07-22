#!/usr/bin/env python3
"""Fail unless extracted V2 critical device terminals match the route intent."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CRITICAL_NETS = (
    "input", "vcm", "tail", "gm_p", "gm_n", "out_p", "out_n", "lop", "lon"
)


def logical_lines(text: str) -> list[str]:
    """Collapse SPICE continuation lines without changing token spelling."""
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not result:
                raise ValueError("SPICE continuation appears before a statement")
            result[-1] += " " + line[1:].strip()
        else:
            result.append(line)
    return result


def top_instances(
    text: str, top: str = "v2_four_channel_critical_routed"
) -> dict[str, list[str]]:
    lines = logical_lines(text)
    inside = False
    instances: dict[str, list[str]] = {}
    for line in lines:
        lower = line.lower()
        if lower == f".subckt {top.lower()}":
            inside = True
            continue
        if inside and lower == ".ends":
            break
        if inside and line[0].upper() == "X":
            tokens = line.split()
            if tokens[0] in instances:
                raise ValueError(f"duplicate extracted instance {tokens[0]}")
            instances[tokens[0]] = tokens[1:-1]
    if not inside:
        raise ValueError(f"missing .subckt {top}")
    return instances


def expected_nodes(
    channel: int,
    substrate_node: str = "VSUBS",
    output_summing: bool = False,
    shared_vcm: bool = False,
) -> dict[str, list[str]]:
    prefix = f"CH{channel}"
    net = lambda name: f"ch{channel}_{name}"
    output_net = (
        (lambda name: f"ch0_{name}") if output_summing else net
    )
    vcm_net = "ch0_vcm" if shared_vcm else net("vcm")
    expected: dict[str, list[str]] = {
        f"X{prefix}_RINPUT": [substrate_node, vcm_net, net("input")],
        f"X{prefix}_PBUF_P": [
            f"{prefix}_PBUF_P/VPWR", f"{prefix}_PBUF_P/VGND", net("lop"),
            f"{prefix}_PBUF_P/A", f"{prefix}_PBUF_P/VPB", substrate_node,
        ],
        f"X{prefix}_PBUF_N": [
            f"{prefix}_PBUF_N/VPWR", f"{prefix}_PBUF_N/VGND", net("lon"),
            f"{prefix}_PBUF_N/A", f"{prefix}_PBUF_N/VPB", substrate_node,
        ],
    }

    for name, drain, gate in (
        ("GM_SIG_A", "gm_p", "input"),
        ("GM_SIG_B", "gm_p", "input"),
        ("GM_REF_A", "gm_n", "vcm"),
        ("GM_REF_B", "gm_n", "vcm"),
    ):
        expected[f"X{prefix}_{name}"] = [
            substrate_node, net(drain),
            vcm_net if gate == "vcm" else net(gate), net("tail"),
            net(drain), net("tail"), net(drain), net("tail"),
        ]

    for name, output, lo, gm in (
        ("SW1_A", "out_p", "lop", "gm_p"),
        ("SW1_B", "out_p", "lop", "gm_p"),
        ("SW2_A", "out_n", "lon", "gm_p"),
        ("SW2_B", "out_n", "lon", "gm_p"),
        ("SW3_A", "out_n", "lop", "gm_n"),
        ("SW3_B", "out_n", "lop", "gm_n"),
        ("SW4_A", "out_p", "lon", "gm_n"),
        ("SW4_B", "out_p", "lon", "gm_n"),
    ):
        expected[f"X{prefix}_{name}"] = [
            substrate_node, output_net(output), net(lo), net(gm),
            output_net(output), net(gm), output_net(output), net(gm),
        ]
    return expected


def expected_output_load_nodes() -> dict[str, list[str]]:
    """Exact shared-load topology at the output-summing checkpoint.

    R2 is the collector/output terminal.  R1 and the guard/body are deliberately
    still private at this checkpoint; the following power-routing stage joins
    R1 to VDD and keeps both bodies at VGND.
    """
    return {
        "XLOAD_P": ["VGND", "LOAD_P/R1", "ch0_out_p"],
        "XLOAD_N": ["VGND", "LOAD_N/R1", "ch0_out_n"],
    }


def expected_support_nodes() -> dict[str, list[str]]:
    """Exact shared VCM and bias-reference topology.

    The upper ends of the VCM divider and RBIAS intentionally remain private
    until the following VDD-grid stage.  All support bodies and the MIM bottom
    plate are already grounded at this checkpoint.
    """
    bias = [
        "VGND", "ch0_vbias", "ch0_vbias", "VGND", "ch0_vbias", "VGND",
        "ch0_vbias", "VGND", "ch0_vbias", "VGND", "ch0_vbias", "VGND",
    ]
    return {
        "XRVCM_BOTTOM": ["VGND", "ch0_vcm", "VGND"],
        "XRVCM_TOP": ["VGND", "RVCM_TOP/R1", "ch0_vcm"],
        "XCVCM": ["VGND", "ch0_vcm", "VGND"],
        "XRBIAS": ["VGND", "RBIAS/R1", "ch0_vbias"],
        "XBIAS_DIODE_A": bias,
        "XBIAS_DIODE_B": bias,
    }


def expected_local_trim_nodes(
    channel: int, shared_vbias: bool = False,
) -> dict[str, list[str]]:
    """Exact local tail-bank/control topology after shared-ground routing."""
    prefix = f"CH{channel}"
    net = lambda name: f"ch{channel}_{name}"
    ground = "VGND"
    tail = net("tail")
    vbias = "ch0_vbias" if shared_vbias else net("vbias")
    expected: dict[str, list[str]] = {}

    # Each 14-finger fixed-bank PCell exposes alternating D/S diffusion ports,
    # one common gate, and the substrate body as its last port.
    main_nodes = [tail, vbias] + [ground, tail] * 6 + [ground, ground]
    for index in range(3):
        expected[f"X{prefix}_TMAIN{index}"] = main_nodes

    trim_fingers = {8: 8, 4: 4, 2: 2}
    for weight, fingers in trim_fingers.items():
        gate = f"{prefix}_TTRIM{weight}/G"
        expected[f"X{prefix}_TTRIM{weight}"] = (
            [tail, gate] + [ground, tail] * (fingers // 2 - 1)
            + [ground, ground]
        )
    # The one-finger cell's extracted port order is D, S, G, B.
    expected[f"X{prefix}_TTRIM1"] = [
        tail, ground, f"{prefix}_TTRIM1/G", ground,
    ]

    weight_for_bit = {3: 8, 2: 4, 1: 2, 0: 1}
    for bit, weight in weight_for_bit.items():
        trim_gate = f"{prefix}_TTRIM{weight}/G"
        expected[f"X{prefix}_TSW{bit}_ON"] = [
            trim_gate, vbias, f"{prefix}_TINV{bit}/A", ground,
        ]
        expected[f"X{prefix}_TSW{bit}_OFF"] = [
            trim_gate, ground, f"{prefix}_TINV{bit}/Y", ground,
        ]

    inverter_power = f"{prefix}_TINV3/VPWR"
    for bit in range(4):
        expected[f"X{prefix}_TINV{bit}"] = [
            f"{prefix}_TINV{bit}/VPB", ground, ground, inverter_power,
            f"{prefix}_TINV{bit}/A", f"{prefix}_TINV{bit}/Y",
        ]
    return expected


def expected_phase_selector_nodes(
    channel: int, global_phase_tree: bool = False,
) -> dict[str, list[str]]:
    """Exact two-stage 4:1 selector and output blanking topology."""
    prefix = f"CH{channel}"
    net = lambda name: f"ch{channel}_{name}"
    phase_net = (
        (lambda name: f"ch0_{name}") if global_phase_tree else net
    )
    expected: dict[str, list[str]] = {}

    for name, phase_a0, phase_a1 in (
        ("PMUX_A", "phase_0_leaf", "phase_90_leaf"),
        ("PMUX_B", "phase_180_leaf", "phase_270_leaf"),
    ):
        expected[f"X{prefix}_{name}"] = [
            f"{prefix}_{name}/VGND", f"{prefix}_{name}/VPWR",
            f"{prefix}_{name}/VPB", "VGND", f"{prefix}_{name}/X",
            phase_net(phase_a1), net("phase_sel0"), phase_net(phase_a0),
        ]

    # The complementary outputs intentionally reverse A0/A1 at the second
    # mux so the P/N pair remains opposite for every two-bit phase code.
    expected[f"X{prefix}_PMUX_P"] = [
        f"{prefix}_PMUX_P/VGND", f"{prefix}_PMUX_P/VPWR",
        f"{prefix}_PMUX_P/VPB", "VGND", f"{prefix}_PMUX_P/X",
        f"{prefix}_PMUX_B/X", net("phase_sel1"), f"{prefix}_PMUX_A/X",
    ]
    expected[f"X{prefix}_PMUX_N"] = [
        f"{prefix}_PMUX_N/VGND", f"{prefix}_PMUX_N/VPWR",
        f"{prefix}_PMUX_N/VPB", "VGND", f"{prefix}_PMUX_N/X",
        f"{prefix}_PMUX_A/X", net("phase_sel1"), f"{prefix}_PMUX_B/X",
    ]

    for polarity in ("P", "N"):
        expected[f"X{prefix}_PAND_{polarity}"] = [
            f"{prefix}_PBUF_{polarity}/VPWR",
            f"{prefix}_PBUF_{polarity}/VGND",
            f"{prefix}_PBUF_{polarity}/A", net("phase_enable"),
            f"{prefix}_PMUX_{polarity}/X",
            f"{prefix}_PBUF_{polarity}/VPB", "VGND",
        ]
    return expected


def check(
    hierarchical: Path,
    flat: Path,
    top: str = "v2_four_channel_critical_routed",
    include_local_trim: bool = False,
    include_phase_selector: bool = False,
    include_global_phase_tree: bool = False,
    include_output_summing: bool = False,
    include_support_network: bool = False,
) -> dict[str, object]:
    hierarchical_text = hierarchical.read_text(encoding="utf-8")
    flat_text = flat.read_text(encoding="utf-8")
    instances = top_instances(hierarchical_text, top)
    failures: list[str] = []
    checked_instances = 0

    for channel in range(4):
        expected_for_channel = expected_nodes(
            channel,
            "VGND" if include_local_trim else "VSUBS",
            include_output_summing,
            include_support_network,
        )
        if include_local_trim:
            expected_for_channel.update(
                expected_local_trim_nodes(channel, include_support_network)
            )
        if include_phase_selector:
            expected_for_channel.update(
                expected_phase_selector_nodes(channel, include_global_phase_tree)
            )
        for name, expected in expected_for_channel.items():
            actual = instances.get(name)
            checked_instances += 1
            if actual is None:
                failures.append(f"missing extracted instance {name}")
            elif actual != expected:
                failures.append(
                    f"{name}: expected {' '.join(expected)}; got {' '.join(actual)}"
                )

    if include_output_summing:
        for name, expected in expected_output_load_nodes().items():
            actual = instances.get(name)
            checked_instances += 1
            if actual is None:
                failures.append(f"missing extracted instance {name}")
            elif actual != expected:
                failures.append(
                    f"{name}: expected {' '.join(expected)}; got {' '.join(actual)}"
                )

    if include_support_network:
        for name, expected in expected_support_nodes().items():
            actual = instances.get(name)
            checked_instances += 1
            if actual is None:
                failures.append(f"missing extracted instance {name}")
            elif actual != expected:
                failures.append(
                    f"{name}: expected {' '.join(expected)}; got {' '.join(actual)}"
                )

    surviving: dict[str, bool] = {}
    for channel in range(4):
        for suffix in CRITICAL_NETS:
            if include_output_summing and suffix in ("out_p", "out_n") and channel:
                # All channel collectors intentionally join the ch0-named
                # shared output conductors at this checkpoint.
                continue
            if include_support_network and suffix == "vcm" and channel:
                # Every channel VCM tap joins the ch0-named shared bus.
                continue
            name = f"ch{channel}_{suffix}"
            present = re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", flat_text) is not None
            surviving[name] = present
            if not present:
                failures.append(f"critical net {name} disappeared from flat extraction")
    if include_local_trim:
        local_nets = ["VGND"] + (
            ["ch0_vbias"] if include_support_network
            else [f"ch{channel}_vbias" for channel in range(4)]
        )
        for name in local_nets:
            present = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                flat_text,
            ) is not None
            surviving[name] = present
            if not present:
                failures.append(f"local routed net {name} disappeared from flat extraction")
    if include_phase_selector:
        phase_suffixes = (
            "phase_0_leaf", "phase_90_leaf", "phase_180_leaf", "phase_270_leaf",
        )
        expected_selector_nets = [
            f"ch{channel}_{suffix}"
            for channel in range(4)
            for suffix in ("phase_sel0", "phase_sel1", "phase_enable")
        ]
        if include_global_phase_tree:
            # Magic deterministically retains the first channel-leaf label on
            # each physically joined tree.  Exact instance checks above prove
            # that every other channel reaches that shared conductor.
            expected_selector_nets.extend(f"ch0_{suffix}" for suffix in phase_suffixes)
        else:
            expected_selector_nets.extend(
                f"ch{channel}_{suffix}"
                for channel in range(4)
                for suffix in phase_suffixes
            )
        for name in expected_selector_nets:
            present = re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                flat_text,
            ) is not None
            surviving[name] = present
            if not present:
                failures.append(
                    f"phase-selector net {name} disappeared from flat extraction"
                )

    report: dict[str, object] = {
        "passed": not failures,
        "checked_instance_count": checked_instances,
        "critical_net_count": len(surviving),
        "critical_nets_survived": all(surviving.values()),
        "included_local_trim": include_local_trim,
        "included_phase_selector": include_phase_selector,
        "included_global_phase_tree": include_global_phase_tree,
        "included_output_summing": include_output_summing,
        "included_support_network": include_support_network,
        "failures": failures,
    }
    if failures:
        raise ValueError("critical extraction topology failed:\n" + "\n".join(failures))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hierarchical", type=Path)
    parser.add_argument("flat", type=Path)
    parser.add_argument("--top", default="v2_four_channel_critical_routed")
    parser.add_argument("--include-local-trim", action="store_true")
    parser.add_argument("--include-phase-selector", action="store_true")
    parser.add_argument("--include-global-phase-tree", action="store_true")
    parser.add_argument("--include-output-summing", action="store_true")
    parser.add_argument("--include-support-network", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check(
        args.hierarchical,
        args.flat,
        args.top,
        args.include_local_trim,
        args.include_phase_selector,
        args.include_global_phase_tree,
        args.include_output_summing,
        args.include_support_network,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
