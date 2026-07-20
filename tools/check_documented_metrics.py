#!/usr/bin/env python3
"""Reject stale human-readable metrics after submission evidence is frozen."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submission"


def read_json(name: str) -> dict[str, object]:
    return json.loads((SUBMISSION / name).read_text(encoding="utf-8"))


def require(text: str, fragment: str, document: str) -> None:
    if fragment not in text:
        raise SystemExit(f"stale {document}: missing {fragment!r}")


def main() -> None:
    datasheet = (ROOT / "docs/datasheet.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs/presilicon_plan.md").read_text(encoding="utf-8")
    frequency = read_json("extracted_frequency_sweep.json")
    clock = read_json("extracted_clock_sweep.json")
    balance = read_json("extracted_channel_balance.json")
    pvt = read_json("extracted_pvt_summary.json")
    independent = read_json("independent_ngspice46_frequency_crosscheck.json")
    core_pvt = read_json("core_pvt_summary.json")
    mismatch = read_json("mismatch_mc_summary.json")
    signoff = read_json("signoff.json")

    for result in frequency["results"]:
        lo = float(result["frequency_mhz"])
        target = "pass" if result["nominal_40db_target_met"] else "miss"
        release = "pass" if result["passed"] else "fail"
        row = (
            f"| {lo:g} MHz | {lo + 1:g} MHz | "
            f"{float(result['sum']['tone_rms']) * 1e3:.4f} mVrms | "
            f"{float(result['null_db']):.2f} dB | {target} | {release} |"
        )
        require(datasheet, row, "datasheet frequency table")

    for result in clock["results"]:
        pair_skew = max(
            float(result["positive_pair_skew_s"]),
            float(result["negative_pair_skew_s"]),
        )
        row = (
            f"| {float(result['frequency_mhz']):g} MHz | "
            f"{float(result['max_edge_s']) * 1e9:.3f} ns | "
            f"{pair_skew * 1e9:.3f} ns | "
            f"{'pass' if result['passed'] else 'fail'} |"
        )
        require(datasheet, row, "datasheet clock table")

    require(
        datasheet,
        f"{float(balance['gain_mismatch_percent']):.7f} percent nominal amplitude",
        "datasheet channel balance",
    )
    require(
        datasheet,
        f"cancellation estimate is {float(balance['estimated_amplitude_only_null_db']):.2f} dB",
        "datasheet channel balance",
    )

    pvt_results = pvt["results"]
    worst = min(pvt_results, key=lambda item: float(item["null_db"]))
    best = max(pvt_results, key=lambda item: float(item["null_db"]))
    sum_rms = [float(item["sum_rms"]) * 1e3 for item in pvt_results]
    common_modes = [
        float(item[key])
        for item in pvt_results
        for key in ("sum_cm", "null_cm")
    ]
    currents = [
        abs(float(item[key])) * 1e3
        for item in pvt_results
        for key in ("sum_supply", "null_supply")
    ]
    worst_headroom = min(
        pvt_results, key=lambda item: float(item["output_high_headroom_v"])
    )
    require(
        datasheet,
        (
            f"| Minimum null | {float(worst['null_db']):.2f} dB at "
            f"{str(worst['corner']).upper()}, {float(worst['supply_v']):.2f} V, "
            f"{int(worst['temperature_c'])} C |"
        ),
        "datasheet PVT table",
    )
    require(
        datasheet,
        f"| Maximum null | {float(best['null_db']):.2f} dB |",
        "datasheet PVT table",
    )
    require(
        datasheet,
        (
            "| Constructive time-domain RMS range | "
            f"{min(sum_rms):.3f} to {max(sum_rms):.3f} mVrms |"
        ),
        "datasheet PVT table",
    )
    require(
        datasheet,
        (
            f"| Output common-mode range | {min(common_modes):.3f} to "
            f"{max(common_modes):.3f} V |"
        ),
        "datasheet PVT table",
    )
    require(
        datasheet,
        (
            f"| Supply-current range | {min(currents):.3f} to "
            f"{max(currents):.3f} mA |"
        ),
        "datasheet PVT table",
    )
    require(
        datasheet,
        (
            f"| Minimum output high-side headroom | "
            f"{float(worst_headroom['output_high_headroom_v']):.3f} V at "
            f"{str(worst_headroom['corner']).upper()}, "
            f"{float(worst_headroom['supply_v']):.2f} V, "
            f"{int(worst_headroom['temperature_c'])} C |"
        ),
        "datasheet PVT table",
    )

    nominal = next(
        item for item in pvt_results if item["case"] == "tt_1.80v_p27c"
    )
    nominal_fragments = (
        f"result is {float(nominal['sum_rms']) * 1e3:.3f} mVrms",
        (
            f"constructive, {float(nominal['null_rms']) * 1e3:.3f} mVrms "
            f"destructive, {float(nominal['null_db']):.2f} dB null, "
            f"{float(nominal['sum_cm']):.3f} V common mode,"
        ),
        f"and {abs(float(nominal['sum_supply'])) * 1e3:.3f} mA.",
    )
    for fragment in nominal_fragments:
        require(datasheet, fragment, "datasheet nominal PVT paragraph")

    nominal_frequency = next(
        item for item in frequency["results"] if item["frequency_mhz"] == 4.0
    )
    require(
        readme,
        f"and {float(nominal_frequency['null_db']):.2f} dB null at a 4 MHz LO;",
        "README nominal result",
    )
    worst_null = float(worst["null_db"])
    require(readme, f"with a {worst_null:.2f} dB worst null;", "README PVT result")
    require(plan, f"45/45 pass, {worst_null:.2f} dB worst null at", "pre-silicon plan")
    core_minimum = min(float(item["null_db"]) for item in core_pvt["results"])
    core_headroom = min(
        float(item["output_high_headroom_v"]) for item in core_pvt["results"]
    )
    require(
        datasheet,
        f"schematic 45-case PVT: 45/45 pass with an {core_minimum:.2f} dB minimum null",
        "datasheet schematic PVT result",
    )
    require(
        plan,
        f"schematic PVT: 45/45 pass with an {core_minimum:.2f} dB minimum null",
        "pre-silicon schematic PVT result",
    )
    for document, text in (("datasheet", datasheet), ("pre-silicon plan", plan)):
        require(
            text,
            f"{core_headroom:.3f} V minimum output high-side headroom",
            f"{document} schematic PVT headroom",
        )
    mismatch_minimum = float(mismatch["minimum_null_db"])
    mismatch_p05 = float(mismatch["p05_null_db"])
    mismatch_median = float(mismatch["median_null_db"])
    require(
        datasheet,
        (
            f"the worst null is {mismatch_minimum:.2f} dB, the\n"
            f"empirical fifth percentile is {mismatch_p05:.2f} dB, and the "
            f"median is {mismatch_median:.2f} dB"
        ),
        "datasheet mismatch result",
    )
    require(
        readme,
        f"with {mismatch_minimum:.2f} dB worst-case",
        "README mismatch result",
    )
    require(
        plan,
        f"30/30 pass, {mismatch_minimum:.2f} dB worst null",
        "pre-silicon mismatch result",
    )

    independent_result = independent["results"][0]
    require(
        datasheet,
        (
            f"measured {float(independent_result['sum']['tone_rms']) * 1e3:.4f} mVrms "
            f"constructive output and {float(independent_result['null_db']):.2f} dB null"
        ),
        "datasheet independent cross-check",
    )

    artifact_labels = {
        "gds": "GDS SHA-256",
        "lef": "LEF SHA-256",
        "extracted_spice": "Extracted SPICE SHA-256",
    }
    for name, label in artifact_labels.items():
        require(
            datasheet,
            f"| {label} | `{signoff['artifacts'][name]['sha256']}` |",
            "datasheet artifact table",
        )

    print(
        "Documented metrics passed: frequency, clock, balance, extracted and "
        "schematic PVT, independent cross-check, and artifact hashes match frozen evidence"
    )


if __name__ == "__main__":
    main()
