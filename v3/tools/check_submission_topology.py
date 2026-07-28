#!/usr/bin/env python3
"""Audit the exact packaged V3 hierarchy and independent flat extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MAGIC_EXTRACTED_PREBOUNDARY_SHA256 = "0226f6da17aa037bcc147c1726c8b1baa01d70c1954981feec709e8475edeee9"
CONNECT_RE = re.compile(r'^(?:merge|equiv) "([^"]+)" "([^"]+)"')
NODE_RE = re.compile(r'^node "([^"]+)"', re.MULTILINE)
HIER_METRICS = {
    "gds_feedback": re.compile(r"V3_SUBMISSION_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_SUBMISSION_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(r"V3_SUBMISSION_EXTRACTION_FEEDBACK_COUNT=(\d+)"),
    "feedback_after_clear": re.compile(r"V3_SUBMISSION_FEEDBACK_AFTER_CLEAR=(\d+)"),
}
FLAT_METRICS = {
    "gds_feedback": re.compile(r"V3_SUBMISSION_FLAT_GDS_FEEDBACK_COUNT=(\d+)"),
    "drc": re.compile(r"V3_SUBMISSION_FLAT_DRC_COUNT=(\d+)"),
    "extraction_feedback": re.compile(r"V3_SUBMISSION_FLAT_EXTRACTION_FEEDBACK_COUNT=(\d+)"),
    "feedback_after_clear": re.compile(r"V3_SUBMISSION_FLAT_FEEDBACK_AFTER_CLEAR=(\d+)"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def root(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.root(self.parent[item])
        return self.parent[item]

    def union(self, first: str, second: str) -> None:
        left, right = self.root(first), self.root(second)
        if left != right:
            self.parent[right] = left


def parse_ext(path: Path) -> tuple[UnionFind, set[str]]:
    text = path.read_text(encoding="utf-8")
    union = UnionFind()
    names = set(NODE_RE.findall(text))
    for line in text.splitlines():
        match = CONNECT_RE.match(line)
        if match:
            first, second = match.groups()
            union.union(first, second)
            names.update((first, second))
    return union, names


def spice_population(path: Path) -> tuple[int, Counter[str], Counter[str]]:
    devices = 0
    models: Counter[str] = Counter()
    terminals: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("X"):
            continue
        tokens = line.split()
        model_index = next(
            index for index, token in enumerate(tokens)
            if token.startswith("sky130_fd_pr__")
        )
        devices += 1
        models[tokens[model_index]] += 1
        terminals.update(tokens[1:model_index])
    return devices, models, terminals


def metrics(path: Path, patterns: dict[str, re.Pattern[str]]) -> dict[str, int | None]:
    text = path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, int | None] = {}
    for name, pattern in patterns.items():
        values = [int(value) for value in pattern.findall(text)]
        result[name] = values[-1] if values else None
    return result


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    package = json.loads(args.package_report.read_text(encoding="utf-8"))
    precheck = json.loads(args.precheck.read_text(encoding="utf-8"))
    candidate_hash = sha256(args.gds)
    source = plan["source_checkpoint"]
    if sha256(ROOT / source["gds"]) != source["sha256"]:
        errors.append("frozen output-tie source differs from the packaging plan")
    if sha256(ROOT / source["physical_gate"]) != source["physical_gate_sha256"]:
        errors.append("frozen output-tie evidence differs from the packaging plan")
    if package.get("status") != "pass" or package.get("submission_sha256") != candidate_hash:
        errors.append("packaging report does not bind the GDS under audit")
    if (
        package.get("magic_extracted_preboundary_sha256")
        != MAGIC_EXTRACTED_PREBOUNDARY_SHA256
        or not package.get("project_boundary_is_non_electrical_only_delta")
    ):
        errors.append("final prBoundary delta is not bound to the Magic-extracted wrapper")
    if package.get("removed_redundant_internal_power_labels") != 2:
        errors.append("packaging did not remove exactly two redundant internal power labels")
    if precheck.get("status") != "pass" or precheck.get("gds_sha256") != candidate_hash:
        errors.append("direct-GDS precheck is stale or not clean")
    if any(item.get("markers") != 0 for item in precheck.get("checks", {}).values()):
        errors.append("one or more direct-GDS checks has markers")

    hierarchical_metrics = metrics(args.magic_log, HIER_METRICS)
    expected_hierarchical = {
        "gds_feedback": 0, "drc": 0,
        "extraction_feedback": 9, "feedback_after_clear": 0,
    }
    if hierarchical_metrics != expected_hierarchical:
        errors.append(f"hierarchical Magic metrics differ: {hierarchical_metrics}")
    flat_metrics = metrics(args.flat_magic_log, FLAT_METRICS)
    expected_flat = {
        "gds_feedback": 0, "drc": 0,
        "extraction_feedback": 36, "feedback_after_clear": 0,
    }
    if flat_metrics != expected_flat:
        errors.append(f"flat Magic metrics differ: {flat_metrics}")
    hierarchical_warning_baseline_exact = (
        args.extraction_feedback.read_bytes() == args.frozen_feedback.read_bytes()
    )
    if not hierarchical_warning_baseline_exact:
        errors.append("hierarchical extraction warnings differ from the frozen baseline")
    flat_feedback_text = args.flat_feedback.read_text(encoding="utf-8")
    flat_missing_terminal_warnings = flat_feedback_text.count("device missing 1 terminal;")
    flat_grounded_warning_targets = re.findall(
        r"connecting remainder to node ([^\"\n]+)", flat_feedback_text
    )
    if flat_missing_terminal_warnings != 36 or len(flat_grounded_warning_targets) != 36:
        errors.append("flat warning population is not the expected four-channel dummy baseline")

    source_count, source_models, source_terminals = spice_population(args.source_spice)
    hier_count, hier_models, hier_terminals = spice_population(args.hier_spice)
    flat_count, flat_models, flat_terminals = spice_population(args.flat_spice)
    if not (
        source_count == hier_count == flat_count == 6037
        and source_models == hier_models == flat_models
    ):
        errors.append("device/model population differs across frozen, packaged, and flat views")

    union, ext_names = parse_ext(args.flat_ext)
    outputs = (
        [f"uo_out[{index}]" for index in range(8)]
        + [f"uio_out[{index}]" for index in range(8)]
        + [f"uio_oe[{index}]" for index in range(8)]
    )
    output_group = {"VGND", *outputs}
    grouped: dict[str, set[str]] = defaultdict(set)
    for name in ext_names | output_group | {"VDPWR"}:
        grouped[union.root(name)].add(name)
    output_root = union.root("VGND")
    extracted_output_group = grouped[output_root] & output_group
    all_outputs_grounded = extracted_output_group == output_group
    if not all_outputs_grounded:
        errors.append("the 24 digital outputs are not all equivalent to VGND in flat extraction")
    if union.root("VDPWR") == output_root:
        errors.append("VDPWR is shorted to the flattened ground/output network")
    unexpected_interface_aliases = sorted(
        name for name in grouped[output_root]
        if name in {
            "clk", "ena", "rst_n", *[f"ui_in[{i}]" for i in range(8)],
            *[f"uio_in[{i}]" for i in range(8)], *[f"ua[{i}]" for i in range(8)],
        }
    )
    if unexpected_interface_aliases:
        errors.append(f"active/unused interface pins were tied to ground: {unexpected_interface_aliases}")

    used_pins = [
        "clk", "ena", "rst_n",
        *[f"ui_in[{index}]" for index in range(8)],
        *[f"uio_in[{index}]" for index in range(3)],
        *[f"ua[{index}]" for index in range(6)],
    ]
    unused_pins = [
        *[f"uio_in[{index}]" for index in range(3, 8)],
        "ua[6]", "ua[7]",
    ]
    used_roots = {union.root(pin) for pin in used_pins}
    if len(used_roots) != len(used_pins):
        errors.append("two or more used interface pins are physically aliased")
    if any(root in {output_root, union.root("VDPWR")} for root in used_roots):
        errors.append("a used interface pin is physically aliased to a supply")
    unused_roots = {union.root(pin) for pin in unused_pins}
    if len(unused_roots) != len(unused_pins):
        errors.append("two or more intentionally unused interface pins are aliased")
    if unused_roots & used_roots or any(
        root in {output_root, union.root("VDPWR")} for root in unused_roots
    ):
        errors.append("an intentionally unused pin is connected to another interface/supply net")

    expected_terminal_hits = {
        "clk": 10, "ena": 2, "rst_n": 14,
        **{f"ui_in[{index}]": 2 for index in range(8)},
        "uio_in[0]": 6, "uio_in[1]": 2, "uio_in[2]": 6,
        **{f"ua[{index}]": 16 for index in range(4)},
        "ua[4]": 122, "ua[5]": 121,
    }
    observed_terminal_hits = {pin: flat_terminals[pin] for pin in used_pins}
    if observed_terminal_hits != expected_terminal_hits:
        errors.append("used interface terminal populations differ from the expected netlist")
    unused_terminal_hits = {pin: flat_terminals[pin] for pin in unused_pins}
    if any(unused_terminal_hits.values()):
        errors.append("an intentionally unused pin reaches an extracted device")

    ground_alias_candidates = set(flat_grounded_warning_targets)
    ground_terminal_aliases = [
        name for name in output_group if flat_terminals[name] == 5242
    ]
    physical_supply_terminal_counts = (
        flat_terminals["VDPWR"] == source_terminals["VDPWR"] == 4818
        and len(ground_terminal_aliases) == 1
        and ground_terminal_aliases[0] in output_group
        and flat_terminals[ground_terminal_aliases[0]] == source_terminals["VGND"] == 5242
        and ground_alias_candidates == {ground_terminal_aliases[0]}
    )
    if not physical_supply_terminal_counts:
        errors.append("flat extraction does not preserve the complete power/ground terminal population")

    return {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "scope": "exact packaged TinyTapeout V3 hierarchy plus independent physically flattened extraction",
        "errors": errors,
        "gds": str(args.gds.relative_to(ROOT)),
        "gds_sha256": candidate_hash,
        "checks": {
            "hierarchical_magic_metrics": hierarchical_metrics,
            "flat_magic_metrics": flat_metrics,
            "hierarchical_warning_baseline_exact": hierarchical_warning_baseline_exact,
            "flat_dummy_warning_count": flat_missing_terminal_warnings,
            "device_count": flat_count,
            "device_model_population_preserved": source_models == hier_models == flat_models,
            "all_24_digital_outputs_tied_to_vgnd": all_outputs_grounded,
            "vdpwr_separate_from_vgnd": union.root("VDPWR") != output_root,
            "ground_net_spice_alias": ground_terminal_aliases[0] if len(ground_terminal_aliases) == 1 else None,
            "vdpwr_terminal_hits": flat_terminals["VDPWR"],
            "vgnd_terminal_hits": flat_terminals[ground_terminal_aliases[0]] if len(ground_terminal_aliases) == 1 else None,
            "used_interface_pins": len(used_pins),
            "distinct_used_interface_roots": len(used_roots),
            "unused_isolated_pins": len(unused_pins),
            "distinct_unused_interface_roots": len(unused_roots),
            "used_terminal_hits": observed_terminal_hits,
            "unused_terminal_hits": unused_terminal_hits,
            "unexpected_interface_aliases_on_ground": unexpected_interface_aliases,
            "direct_gds_precheck_zero": precheck.get("status") == "pass",
            "magic_extracted_preboundary_sha256": package.get("magic_extracted_preboundary_sha256"),
            "final_delta_is_only_non_electrical_prboundary": package.get("project_boundary_is_non_electrical_only_delta"),
        },
        "artifact_sha256": {
            "plan": sha256(args.plan),
            "package_report": sha256(args.package_report),
            "gds": candidate_hash,
            "precheck": sha256(args.precheck),
            "hierarchical_magic_log": sha256(args.magic_log),
            "flat_magic_log": sha256(args.flat_magic_log),
            "hierarchical_feedback": sha256(args.extraction_feedback),
            "flat_feedback": sha256(args.flat_feedback),
            "hierarchical_spice": sha256(args.hier_spice),
            "flat_ext": sha256(args.flat_ext),
            "flat_spice": sha256(args.flat_spice),
            "source_spice": sha256(args.source_spice),
            "auditor": sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/v3/submission"
    parser.add_argument("--plan", type=Path, default=ROOT / "v3/layout/submission_packaging_plan.json")
    parser.add_argument("--package-report", type=Path, default=base / "gds_packaging.json")
    parser.add_argument("--gds", type=Path, default=base / "tt_um_jjassonn69_beamformer.gds")
    parser.add_argument("--precheck", type=Path, default=base / "precheck_final/precheck_summary.json")
    parser.add_argument("--magic-log", type=Path, default=base / "magic_readback.log")
    parser.add_argument("--flat-magic-log", type=Path, default=base / "magic_flat.log")
    parser.add_argument("--extraction-feedback", type=Path, default=base / "magic_readback/extraction_feedback.txt")
    parser.add_argument("--flat-feedback", type=Path, default=base / "magic_flat/extraction_feedback.txt")
    parser.add_argument("--frozen-feedback", type=Path, default=ROOT / "v3/frozen/digital_output_tie/extraction_feedback.txt")
    parser.add_argument("--hier-spice", type=Path, default=base / "magic_readback/tt_um_jjassonn69_beamformer_flat.spice")
    parser.add_argument("--flat-ext", type=Path, default=base / "magic_flat/tt_um_jjassonn69_beamformer_magic_flat.ext")
    parser.add_argument("--flat-spice", type=Path, default=base / "magic_flat/tt_um_jjassonn69_beamformer_magic_flat.spice")
    parser.add_argument("--source-spice", type=Path, default=ROOT / "v3/frozen/digital_output_tie/v3_four_ch_output_tied_flat.spice")
    parser.add_argument("--output", type=Path, default=base / "topology_audit.json")
    args = parser.parse_args()
    report = validate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
