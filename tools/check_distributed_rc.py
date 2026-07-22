#!/usr/bin/env python3
"""Prove that Magic emitted a distributed route-RC simulation netlist.

This is intentionally separate from the device-topology checker.  A netlist
can contain every device and every extracted capacitor while still omitting
the ``.res.ext`` resistor graph; calling that result "full parasitic" would be
misleading.  This gate compares the ordinary extraction with the RC view and
also checks that every manifest net participates in the resistor graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "layout" / "circuit.json"
INTERNAL_NODE_RE = re.compile(r"(?:[/.])(?:n|t)\d+$")
ATTRIBUTE_NODE_RE = re.compile(r"^res:", re.IGNORECASE)


def canonical_net(net: str) -> str:
    return "ui_in[0]" if net == "select" else net


def resistor_node_aliases(node: str) -> set[str]:
    """Return physical-net names represented by an RC split-node token.

    Magic appends ``.n#``/``.t#`` (or slash variants) when a conductor is
    divided into a resistor graph.  Flattened standard-cell supply nodes can
    additionally retain a hierarchy prefix, for example
    ``CH0_PBUF_N.VGND.n1``.  Both spellings still anchor the same physical
    routed net and must count toward coverage without rewriting the SPICE.
    """

    base = INTERNAL_NODE_RE.sub("", node)
    aliases = {base}
    for separator in ("/", "."):
        if separator in base:
            aliases.add(base.rsplit(separator, 1)[-1])
    return aliases


def manifest_nets(path: Path = MANIFEST) -> set[str]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return {
        canonical_net(net)
        for device in manifest["devices"]
        for net in device["nets"].values()
    }


def spice_elements(path: Path) -> dict[str, list[list[str]]]:
    elements = {"R": [], "C": [], "X": []}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line[0] in "*.+":
            continue
        kind = line[0].upper()
        if kind in elements:
            elements[kind].append(line.split())
    return elements


def annotation_counts(path: Path) -> tuple[int, int]:
    rnodes = 0
    resistors = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("rnode "):
            rnodes += 1
        elif line.startswith("resist "):
            resistors += 1
    return rnodes, resistors


def top_ext_for(annotation: Path) -> Path:
    suffix = ".full.res.ext" if annotation.name.endswith(".full.res.ext") else ".res.ext"
    return annotation.with_name(annotation.name.removesuffix(suffix) + ".ext")


def rc_details(rc: dict[str, list[list[str]]], expected_nets: set[str]) -> dict[str, object]:
    resistor_terminals: set[str] = set()
    parents: dict[str, str] = {}

    def find(node: str) -> str:
        parents.setdefault(node, node)
        if parents[node] != node:
            parents[node] = find(parents[node])
        return parents[node]

    def union(first: str, second: str) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    malformed_resistors: list[str] = []
    nonpositive_resistors: list[str] = []
    for fields in rc["R"]:
        if len(fields) < 4:
            malformed_resistors.append(" ".join(fields))
            continue
        resistor_terminals.update(fields[1:3])
        union(fields[1], fields[2])
        try:
            if float(fields[3]) <= 0.0:
                nonpositive_resistors.append(" ".join(fields))
        except ValueError:
            malformed_resistors.append(" ".join(fields))
    terminal_aliases = {
        alias
        for node in resistor_terminals
        for alias in resistor_node_aliases(node)
    }
    uncovered_nets = sorted(expected_nets - terminal_aliases)
    internal_nodes = {node for node in resistor_terminals if INTERNAL_NODE_RE.search(node)}
    attribute_nodes = sorted(
        node for node in resistor_terminals if ATTRIBUTE_NODE_RE.match(node)
    )
    components: dict[str, set[str]] = {}
    for node in resistor_terminals:
        components.setdefault(find(node), set()).add(node)
    unanchored = [
        sorted(component)[:10]
        for component in components.values()
        if not {
            alias
            for member in component
            for alias in resistor_node_aliases(member)
        }.intersection(expected_nets)
    ]
    return {
        "resistors": len(rc["R"]),
        "capacitors": len(rc["C"]),
        "devices": len(rc["X"]),
        "internal_resistor_nodes": len(internal_nodes),
        "attribute_like_resistor_nodes": attribute_nodes,
        "resistor_components": len(components),
        "unanchored_resistor_components": unanchored,
        "covered_manifest_nets": len(expected_nets) - len(uncovered_nets),
        "uncovered_manifest_nets": uncovered_nets,
        "malformed_resistors": malformed_resistors[:10],
        "nonpositive_resistors": nonpositive_resistors[:10],
    }


def audit(
    base_path: Path,
    rc_path: Path,
    top_res_ext: Path,
    simulation_rc_path: Path | None = None,
    simulation_res_ext: Path | None = None,
) -> dict[str, object]:
    base = spice_elements(base_path)
    rc = spice_elements(rc_path)
    rnodes, annotated_resistors = annotation_counts(top_res_ext)
    expected_nets = manifest_nets()
    top_ext = top_ext_for(top_res_ext)
    full = rc_details(rc, expected_nets)
    checks = {
        "base_is_resistance_free_reference": len(base["R"]) == 0,
        "top_resistance_annotation_exists": rnodes > 0 and annotated_resistors > 0,
        "top_resistance_annotation_is_fresh": (
            top_ext.is_file()
            and top_res_ext.stat().st_mtime_ns >= top_ext.stat().st_mtime_ns
        ),
        "explicit_resistors_emitted": full["resistors"] >= annotated_resistors > 0,
        "distributed_capacitances_emitted": full["capacitors"] > len(base["C"]),
        "device_count_preserved": full["devices"] == len(base["X"]) > 0,
        "all_manifest_nets_resistively_covered": not full["uncovered_manifest_nets"],
        "all_resistor_components_manifest_anchored": not full[
            "unanchored_resistor_components"
        ],
        "internal_resistor_nodes_emitted": (
            full["internal_resistor_nodes"] >= len(expected_nets)
        ),
        "resistor_records_well_formed": not full["malformed_resistors"],
        "resistor_values_positive": not full["nonpositive_resistors"],
        "no_extraction_attribute_nodes": not full[
            "attribute_like_resistor_nodes"
        ],
    }
    report: dict[str, object] = {
        "base_netlist": str(base_path),
        "distributed_rc_netlist": str(rc_path),
        "top_resistance_annotation": str(top_res_ext),
        "top_device_annotation": str(top_ext),
        "sha256": {
            "base_netlist": hashlib.sha256(base_path.read_bytes()).hexdigest(),
            "distributed_rc_netlist": hashlib.sha256(rc_path.read_bytes()).hexdigest(),
            "top_resistance_annotation": hashlib.sha256(
                top_res_ext.read_bytes()
            ).hexdigest(),
        },
        "base": {
            "resistors": len(base["R"]),
            "capacitors": len(base["C"]),
            "devices": len(base["X"]),
        },
        "distributed_rc": full,
        "annotation": {"rnodes": rnodes, "resistors": annotated_resistors},
        "manifest_net_count": len(expected_nets),
        "uncovered_manifest_nets": full["uncovered_manifest_nets"],
        "malformed_resistors": full["malformed_resistors"],
        "nonpositive_resistors": full["nonpositive_resistors"],
        "checks": checks,
    }
    if simulation_rc_path is not None and simulation_res_ext is not None:
        simulation_rc = spice_elements(simulation_rc_path)
        simulation = rc_details(simulation_rc, expected_nets)
        simulation_rnodes, simulation_annotated = annotation_counts(simulation_res_ext)
        simulation_top_ext = top_ext_for(simulation_res_ext)
        simulation_checks = {
            "simulation_annotation_exists": (
                simulation_rnodes > 0 and simulation_annotated > 0
            ),
            "simulation_annotation_is_fresh": (
                simulation_top_ext.is_file()
                and simulation_res_ext.stat().st_mtime_ns
                >= simulation_top_ext.stat().st_mtime_ns
            ),
            "simulation_resistors_emitted": simulation["resistors"] > 0,
            "simulation_capacitances_emitted": simulation["capacitors"] > len(base["C"]),
            "simulation_device_count_preserved": simulation["devices"] == len(base["X"]),
            "simulation_network_reduced": (
                simulation["resistors"] < full["resistors"]
                and simulation["internal_resistor_nodes"] < full["internal_resistor_nodes"]
            ),
            "simulation_manifest_net_coverage": (
                simulation["covered_manifest_nets"] >= 0.75 * len(expected_nets)
            ),
            "simulation_components_manifest_anchored": not simulation[
                "unanchored_resistor_components"
            ],
            "simulation_resistors_well_formed": not simulation["malformed_resistors"],
            "simulation_resistors_positive": not simulation["nonpositive_resistors"],
        }
        checks.update(simulation_checks)
        report.update({
            "simulation_rc_netlist": str(simulation_rc_path),
            "simulation_resistance_annotation": str(simulation_res_ext),
            "simulation_distributed_rc": simulation,
            "simulation_annotation": {
                "rnodes": simulation_rnodes,
                "resistors": simulation_annotated,
            },
        })
    report["passed"] = all(checks.values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_netlist", type=Path)
    parser.add_argument("rc_netlist", type=Path)
    parser.add_argument("top_res_ext", type=Path)
    parser.add_argument("simulation_rc_netlist", type=Path, nargs="?")
    parser.add_argument("simulation_top_res_ext", type=Path, nargs="?")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(
        args.base_netlist,
        args.rc_netlist,
        args.top_res_ext,
        args.simulation_rc_netlist,
        args.simulation_top_res_ext,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    counts = report["distributed_rc"]
    annotation = report["annotation"]
    print(
        "Distributed-RC extraction "
        + ("passed" if report["passed"] else "FAILED")
        + f": {counts['resistors']} SPICE resistors, "
        + f"{counts['capacitors']} capacitors, "
        + f"{counts['internal_resistor_nodes']} internal resistor nodes, "
        + f"{counts['resistor_components']} anchored resistor components, "
        + f"{annotation['resistors']} top-level route annotations"
    )
    if "simulation_distributed_rc" in report:
        simulation = report["simulation_distributed_rc"]
        print(
            "Reduced simulation RC: "
            f"{simulation['resistors']} resistors, "
            f"{simulation['capacitors']} capacitors, "
            f"{simulation['internal_resistor_nodes']} internal nodes, "
            f"{simulation['covered_manifest_nets']}/{report['manifest_net_count']} "
            "manifest nets retain explicit R"
        )
    if not report["passed"]:
        for name, passed in report["checks"].items():
            if not passed:
                print(f"FAIL: {name}")
        if report["uncovered_manifest_nets"]:
            print("Uncovered nets: " + ", ".join(report["uncovered_manifest_nets"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
