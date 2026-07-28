#!/usr/bin/env python3
"""Audit V3 tail-reference distributed RC and four-way branch matching."""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK = ROOT / "build" / "v3" / "tail_reference_pilot" / "rc"
DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "bias_distribution.json"
DEFAULT_GDS = ROOT / "build" / "v3" / "tail_reference_pilot" / "v3_tail_reference_pilot.gds"
DEFAULT_REPORT = ROOT / "v3" / "evidence" / "tail_reference_physical_gate.json"
INTERNAL_UNITS_PER_UM = 200
MAX_BRANCH_MISMATCH_PERCENT = 1.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spice_number(token: str) -> float:
    suffixes = {
        "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
        "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
    }
    match = re.fullmatch(r"([-+0-9.eE]+)([A-Za-z]+)?", token)
    if not match:
        raise ValueError(f"invalid SPICE number: {token}")
    value = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    return value * suffixes.get(suffix, 1.0)


def parse_spice(path: Path) -> dict[str, list[list[str]]]:
    result = {"R": [], "C": [], "X": []}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in "*.+":
            continue
        kind = line[0].upper()
        if kind in result:
            result[kind].append(line.split())
    return result


def parse_rnodes(path: Path) -> dict[tuple[int, int], list[str]]:
    pattern = re.compile(
        r'^rnode "([^"]+)"\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\S+$'
    )
    result: dict[tuple[int, int], list[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            result.setdefault((int(match.group(2)), int(match.group(3))), []).append(match.group(1))
    return result


def marker(log: str, name: str) -> int | None:
    matches = re.findall(rf"^{name}=(\d+)\s*$", log, flags=re.MULTILINE)
    return int(matches[-1]) if matches else None


def resistor_graph(records: list[list[str]]) -> dict[str, dict[str, float]]:
    graph: dict[str, dict[str, float]] = {}
    for fields in records:
        if len(fields) < 4:
            raise ValueError(f"malformed resistor record: {' '.join(fields)}")
        first, second = fields[1:3]
        resistance = spice_number(fields[3])
        if not math.isfinite(resistance) or resistance <= 0:
            raise ValueError(f"non-positive resistor: {' '.join(fields)}")
        conductance = 1.0 / resistance
        graph.setdefault(first, {})[second] = graph.setdefault(first, {}).get(second, 0.0) + conductance
        graph.setdefault(second, {})[first] = graph.setdefault(second, {}).get(first, 0.0) + conductance
    return graph


def component(graph: dict[str, dict[str, float]], start: str) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, {}):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def effective_resistance(graph: dict[str, dict[str, float]], source: str, sink: str) -> float:
    """Solve the sparse resistor Laplacian with 1 A source and grounded sink."""
    nodes = sorted(component(graph, source) - {sink})
    if sink not in component(graph, source):
        raise ValueError(f"RC endpoints are disconnected: {source}, {sink}")
    index = {node: i for i, node in enumerate(nodes)}

    def multiply(vector: list[float]) -> list[float]:
        output = [0.0] * len(nodes)
        for node, i in index.items():
            for neighbor, conductance in graph[node].items():
                output[i] += conductance * vector[i]
                if neighbor != sink:
                    output[i] -= conductance * vector[index[neighbor]]
        return output

    b = [0.0] * len(nodes)
    b[index[source]] = 1.0
    x = [0.0] * len(nodes)
    residual = b[:]
    direction = residual[:]
    residual_norm = sum(value * value for value in residual)
    initial_norm = residual_norm
    for _ in range(max(100, 20 * len(nodes))):
        product = multiply(direction)
        denominator = sum(a * value for a, value in zip(direction, product))
        if denominator <= 0:
            raise ValueError("resistor Laplacian is not positive definite")
        alpha = residual_norm / denominator
        x = [value + alpha * step for value, step in zip(x, direction)]
        residual = [value - alpha * step for value, step in zip(residual, product)]
        new_norm = sum(value * value for value in residual)
        if new_norm <= max(1e-28, initial_norm * 1e-20):
            return x[index[source]]
        beta = new_norm / residual_norm
        direction = [value + beta * step for value, step in zip(residual, direction)]
        residual_norm = new_norm
    raise ValueError("effective-resistance solver did not converge")


def point_to_internal(point: list[float]) -> tuple[int, int]:
    return tuple(round(value * INTERNAL_UNITS_PER_UM) for value in point)  # type: ignore[return-value]


def endpoint_nodes(
    rnodes: dict[tuple[int, int], list[str]], graph: dict[str, dict[str, float]], point: list[float]
) -> list[str]:
    coordinate = point_to_internal(point)
    candidates = sorted({node for node in rnodes.get(coordinate, []) if node in graph})
    if not candidates:
        raise ValueError(f"expected resistor node at {point} ({coordinate}), found none")
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--log", type=Path, default=DEFAULT_WORK / "magic_rc.log")
    parser.add_argument("--precheck", type=Path, default=ROOT / "build" / "v3" / "tail_reference_pilot" / "precheck_summary.json")
    parser.add_argument("--topology", type=Path, default=ROOT / "build" / "v3" / "tail_reference_pilot" / "topology_audit.json")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    topology = json.loads(args.topology.read_text(encoding="utf-8"))
    log = args.log.read_text(encoding="utf-8", errors="replace")
    star = data["bias_tree"]["root"]
    common_end = data["common_route"]["start"]
    branches: dict[str, dict[str, object]] = {}
    resistances = []
    artifact_hashes: dict[str, dict[str, str]] = {}
    base_counts = {"resistors": 0, "capacitors": 0, "devices": 0}
    rc_counts = {"resistors": 0, "capacitors": 0, "devices": 0}

    common_base_path = args.work / "tail_reference_common_base.spice"
    common_rc_path = args.work / "tail_reference_common_rc.spice"
    common_res_ext_path = args.work / "v3_tail_reference_pilot_rc_common.res.ext"
    common_base = parse_spice(common_base_path)
    common_rc = parse_spice(common_rc_path)
    common_graph = resistor_graph(common_rc["R"])
    common_rnodes = parse_rnodes(common_res_ext_path)
    common_source_candidates = endpoint_nodes(common_rnodes, common_graph, star)
    common_end_candidates = endpoint_nodes(common_rnodes, common_graph, common_end)
    common_candidate_resistances = {
        f"{source}->{end}": effective_resistance(common_graph, source, end)
        for source in common_source_candidates
        for end in common_end_candidates
        if end in component(common_graph, source)
    }
    if not common_candidate_resistances:
        raise ValueError("common route has no connected reference-side endpoint")
    # The root coordinate contains both the M2-side node and an upper via-stack
    # node.  The larger candidate includes the entire M2-to-M4 root transition,
    # which is the correct common impedance to subtract from leaf-to-reference
    # paths when defining the post-star M2 branch resistance.
    common_pair, common_resistance = max(
        common_candidate_resistances.items(), key=lambda item: item[1]
    )
    common_source, common_end_node = common_pair.split("->", 1)
    artifact_hashes["common"] = {
        "base_spice": sha256(common_base_path),
        "distributed_rc_spice": sha256(common_rc_path),
        "resistance_annotation": sha256(common_res_ext_path),
    }
    base_counts = {
        "resistors": len(common_base["R"]),
        "capacitors": len(common_base["C"]),
        "devices": len(common_base["X"]),
    }
    rc_counts = {
        "resistors": len(common_rc["R"]),
        "capacitors": len(common_rc["C"]),
        "devices": len(common_rc["X"]),
    }
    for channel, point in sorted(data["bias_tree"]["leaves"].items(), key=lambda item: int(item[0])):
        token = f"ch{channel}"
        base_path = args.work / f"tail_reference_{token}_base.spice"
        rc_path = args.work / f"tail_reference_{token}_rc.spice"
        res_ext_path = args.work / f"v3_tail_reference_pilot_rc_{token}.res.ext"
        base = parse_spice(base_path)
        rc = parse_spice(rc_path)
        graph = resistor_graph(rc["R"])
        rnodes = parse_rnodes(res_ext_path)
        leaf_candidates = endpoint_nodes(rnodes, graph, point)
        if len(leaf_candidates) != 1:
            raise ValueError(f"channel {channel} leaf has ambiguous RC nodes: {leaf_candidates}")
        leaf_node = leaf_candidates[0]
        end_candidates = endpoint_nodes(rnodes, graph, common_end)
        total_candidate_resistances = {
            node: effective_resistance(graph, leaf_node, node)
            for node in end_candidates if node in component(graph, leaf_node)
        }
        if not total_candidate_resistances:
            raise ValueError(f"channel {channel} has no connected common-route endpoint")
        end_node, total_resistance = min(
            total_candidate_resistances.items(), key=lambda item: item[1]
        )
        resistance = total_resistance - common_resistance
        if resistance <= 0:
            raise ValueError(f"channel {channel} derived branch resistance is non-positive")
        resistances.append(resistance)
        branches[channel] = {
            "leaf_um": point,
            "leaf_node": leaf_node,
            "common_end_node": end_node,
            "total_leaf_to_reference_side_resistance_ohm": total_resistance,
            "subtracted_common_route_resistance_ohm": common_resistance,
            "effective_resistance_ohm": resistance,
            "base": {
                "resistors": len(base["R"]),
                "capacitors": len(base["C"]),
                "devices": len(base["X"]),
            },
            "distributed_rc": {
                "resistors": len(rc["R"]),
                "capacitors": len(rc["C"]),
                "devices": len(rc["X"]),
            },
        }
        base_counts = {
            key: base_counts[key] + len(base[{"resistors": "R", "capacitors": "C", "devices": "X"}[key]])
            for key in base_counts
        }
        rc_counts = {
            key: rc_counts[key] + len(rc[{"resistors": "R", "capacitors": "C", "devices": "X"}[key]])
            for key in rc_counts
        }
        artifact_hashes[token] = {
            "base_spice": sha256(base_path),
            "distributed_rc_spice": sha256(rc_path),
            "resistance_annotation": sha256(res_ext_path),
        }
    mean = sum(resistances) / len(resistances)
    mismatch = 100.0 * (max(resistances) - min(resistances)) / mean
    warnings = [line.strip() for line in log.splitlines() if line.lstrip().startswith("Warning:")]
    allowed_warning = re.compile(
        r'^(?:Warning:\s+Calma reading is not undoable!  I hope that.s OK\.|'
        r'Warning:\s+Extract option "do unique" disabled because "extract unique" was run\.)$'
    )
    unexpected_warnings = [line for line in warnings if not allowed_warning.fullmatch(line)]
    checks = {
        "magic_drc_zero": all(
            marker(log, f"V3_TAIL_REFERENCE_RC_DRC_COUNT_{token}") == 0
            for token in ("common", "ch0", "ch1", "ch2", "ch3")
        ),
        "magic_extraction_feedback_zero": all(
            marker(log, f"V3_TAIL_REFERENCE_RC_EXTRACTION_FEEDBACK_COUNT_{token}") == 0
            for token in ("common", "ch0", "ch1", "ch2", "ch3")
        ),
        "magic_outputs_complete": log.count("exttospice finished.") >= 10,
        "only_classified_magic_warnings": not unexpected_warnings,
        "base_is_resistance_free": base_counts["resistors"] == 0,
        "distributed_resistors_present": rc_counts["resistors"] > 0,
        # extresist splits conductor resistance; the ordinary extraction has
        # already emitted this pilot's five capacitances.  They must survive
        # unchanged rather than being silently lost or double-counted.
        "extracted_capacitances_preserved": (
            rc_counts["capacitors"] == base_counts["capacitors"] > 0
        ),
        "device_count_preserved": base_counts["devices"] == rc_counts["devices"] == 40,
        "all_four_branch_endpoints_found": len(branches) == 4,
        "branch_resistance_mismatch_within_limit": mismatch <= MAX_BRANCH_MISMATCH_PERCENT,
        "direct_gds_precheck_zero": precheck["status"] == "pass" and all(
            item["markers"] == 0 for item in precheck["checks"].values()
        ),
        "precheck_is_for_exact_gds": precheck["gds_sha256"] == sha256(args.gds),
        "extracted_device_topology_passes": topology["status"] == "pass",
        "topology_is_for_exact_gds": topology["sha256"]["gds"] == sha256(args.gds),
    }
    report = {
        "schema_version": 1,
        "status": "pass" if all(checks.values()) else "fail",
        "scope": "exact V3 shared tail-reference pilot: topology, direct-GDS geometry, and distributed star-to-leaf RC; VCM, decap, channel devices, and top-level integration remain separate gates",
        "checks": checks,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": sha256(args.gds),
        "manifest_sha256": sha256(args.manifest),
        "distributed_rc": {
            "aggregate_base": base_counts,
            "aggregate_distributed_rc": rc_counts,
            "star_um": star,
            "common_route_reference_side_um": common_end,
            "common_route": {
                "source_node": common_source,
                "end_node": common_end_node,
                "end_candidate_resistances_ohm": common_candidate_resistances,
                "effective_resistance_ohm": common_resistance,
            },
            "branches": branches,
            "mean_branch_resistance_ohm": mean,
            "branch_resistance_mismatch_percent": mismatch,
            "maximum_allowed_mismatch_percent": MAX_BRANCH_MISMATCH_PERCENT,
        },
        "unexpected_magic_warnings": unexpected_warnings,
        "sha256": {
            "per_channel": artifact_hashes,
            "magic_log": sha256(args.log),
            "precheck_summary": sha256(args.precheck),
            "topology_audit": sha256(args.topology),
            "extractor": sha256(ROOT / "v3" / "layout" / "extract_tail_reference_rc.tcl"),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
