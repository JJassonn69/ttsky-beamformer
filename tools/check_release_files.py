#!/usr/bin/env python3
"""Dependency-free integrity checks for committed TinyTapeout release files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "submission/template.lock"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    values: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value

    for kind in ("gds", "lef"):
        path = ROOT / values[f"{kind}_file"]
        actual = digest(path)
        expected = values[f"{kind}_sha256"]
        if actual != expected:
            raise SystemExit(f"{kind.upper()} SHA-256 mismatch: {actual} != {expected}")

    signoff = json.loads((ROOT / "submission/signoff.json").read_text(encoding="utf-8"))
    for kind in ("gds", "lef"):
        if signoff["artifacts"][kind]["sha256"] != values[f"{kind}_sha256"]:
            raise SystemExit(f"{kind.upper()} signoff hash does not match template.lock")
    physical = signoff["physical"]
    zero_count_gates = (
        "extraction_feedback_count",
        "flattened_gds_capm_spacing_count",
        "flattened_gds_met3_spacing_count",
        "flattened_gds_met4_area_count",
        "flattened_gds_met4_spacing_count",
        "flattened_gds_met4_width_count",
        "gds_writer_feedback_count",
        "magic_gds_readback_drc_count",
        "magic_internal_signoff_drc_count",
    )
    nonzero = {name: physical[name] for name in zero_count_gates if physical[name] != 0}
    if nonzero:
        raise SystemExit(f"physical signoff contains nonzero error counts: {nonzero}")
    pvt = signoff["electrical"]["extracted_pvt"]
    if pvt["pass_count"] != pvt["case_count"]:
        raise SystemExit("extracted PVT signoff is not fully passing")
    if pvt["case_count"] != 45:
        raise SystemExit(f"extracted PVT has {pvt['case_count']} cases, expected 45")
    for name in ("frequency_sweep", "clock_sweep", "mismatch_surrogate"):
        evidence = signoff["electrical"][name]
        if evidence["pass_count"] != evidence["case_count"]:
            raise SystemExit(f"{name} signoff is not fully passing")
    if signoff["physical"]["extracted_mos_fingers"] != 338:
        raise SystemExit("release does not contain the 338-finger matched layout")
    if signoff["physical"]["placed_devices"] != 70:
        raise SystemExit("release does not contain the 70-device matched layout")
    for report in signoff["reports"].values():
        report_path = ROOT / report["path"]
        if digest(report_path) != report["sha256"]:
            raise SystemExit(f"signoff report hash mismatch: {report_path}")

    gds = (ROOT / values["gds_file"]).read_bytes()
    if not gds.startswith(b"\x00\x06\x00\x02"):
        raise SystemExit("GDS is not an uncompressed GDSII stream")

    lef = (ROOT / values["lef_file"]).read_text(encoding="utf-8")
    top = "tt_um_jjassonn69_beamformer"
    if f"MACRO {top}" not in lef or f"END {top}" not in lef:
        raise SystemExit("LEF top macro is missing or misnamed")
    if "SIZE 161.000 BY 225.760 ;" not in lef:
        raise SystemExit("LEF macro dimensions do not match the 1x2 boundary")
    pin_count = len(re.findall(r"^\s*PIN \S+", lef, re.MULTILINE))
    if pin_count != 53:
        raise SystemExit(f"LEF contains {pin_count} pins, expected 51 template + 2 power")

    required = [
        ROOT / "info.yaml",
        ROOT / "src/project.v",
        ROOT / "docs/info.md",
        ROOT / "docs/datasheet.md",
        ROOT / "docs/images/beamformer-gds.png",
        ROOT / "docs/images/beamformer-core-detail.png",
        ROOT / "docs/images/beamformer-mim-detail.png",
        ROOT / "LICENSE",
        ROOT / "submission/official_magic_drc.txt",
        ROOT / "submission/core_pvt_summary.json",
        ROOT / "submission/extracted_pvt_summary.json",
        ROOT / "submission/extracted_frequency_sweep.json",
        ROOT / "submission/extracted_clock_sweep.json",
        ROOT / "submission/extracted_channel_balance.json",
        ROOT / "submission/mismatch_mc_summary.json",
        ROOT / "submission/signoff.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"required submission files missing: {missing}")

    print(
        "Release files passed: authenticated GDS/LEF hashes, plain GDSII, "
        "161x225.76 um macro, 53 LEF pins, zero physical error counts, "
        "45/45 extracted PVT, 4/4 frequency/clock sweeps, mismatch evidence, "
        "and required metadata"
    )


if __name__ == "__main__":
    main()
