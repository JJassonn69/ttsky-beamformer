#!/usr/bin/env python3
"""Run the post-layout testbench against a selected extracted netlist."""

from __future__ import annotations

import argparse
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from run_lock import acquire_run_lock
except ModuleNotFoundError:
    from tools.run_lock import acquire_run_lock

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "spice" / "sky130" / "extracted_core_tb.spice"
MEASURE_BLOCK = (
    ".measure tran sum_rms rms v(filtered) from=15u to=25u\n"
    ".measure tran null_rms rms v(filtered) from=40u to=50u\n"
    ".measure tran sum_cm avg v(common_mode) from=15u to=25u\n"
    ".measure tran null_cm avg v(common_mode) from=40u to=50u\n"
    ".measure tran sum_supply avg i(VDD) from=15u to=25u\n"
    ".measure tran null_supply avg i(VDD) from=40u to=50u"
)


def measure(path: Path, name: str) -> float:
    match = re.search(
        rf"^\s*{re.escape(name)}\s*=\s*([-+0-9.eE]+)",
        path.read_text(errors="replace"),
        re.MULTILINE,
    )
    if not match:
        raise SystemExit(f"missing {name} in {path}")
    return float(match.group(1))


def run_deck(ngspice: str, deck: Path, log: Path) -> int:
    return subprocess.run(
        [ngspice, "-b", "-o", str(log), str(deck.relative_to(ROOT))],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    ).returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netlist", default="build/layout/extracted_rc.spice")
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--name", default="extracted_core")
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--select", choices=("0", "1"))
    args = parser.parse_args()
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    run_lock = acquire_run_lock(build / f".{args.name}.run.lock")
    deck = build / f"{args.name}.spice"
    log = build / f"{args.name}.log"
    text = TEMPLATE.read_text().replace(
        '.include "build/layout/extracted.spice"', f'.include "{args.netlist}"'
    )
    if args.select is None and not args.reverse:
        values: dict[str, float] = {}
        result = 0
        mode_measures = (
            ".measure tran mode_rms rms v(filtered) from=10u to=20u\n"
            ".measure tran mode_cm avg v(common_mode) from=10u to=20u\n"
            ".measure tran mode_supply avg i(VDD) from=10u to=20u"
        )
        mode_jobs: list[tuple[str, Path, Path]] = []
        for mode, select in (("sum", "0"), ("null", "{VDDVAL}")):
            mode_text = re.sub(
                r"^VSEL ui_in\[0\].*$",
                f"VSEL ui_in[0] 0 {select}",
                text,
                flags=re.MULTILINE,
            ).replace(MEASURE_BLOCK, mode_measures).replace(
                ".tran 2n 50u 15u", ".tran 2n 20u 10u"
            )
            mode_deck = build / f"{args.name}_{mode}.spice"
            mode_log = build / f"{args.name}_{mode}.log"
            mode_deck.write_text(mode_text)
            mode_jobs.append((mode, mode_deck, mode_log))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                mode: executor.submit(run_deck, args.ngspice, mode_deck, mode_log)
                for mode, mode_deck, mode_log in mode_jobs
            }
            for mode, _mode_deck, mode_log in mode_jobs:
                returncode = futures[mode].result()
                result |= returncode
                if returncode:
                    continue
                values[f"{mode}_rms"] = measure(mode_log, "mode_rms")
                values[f"{mode}_cm"] = measure(mode_log, "mode_cm")
                values[f"{mode}_supply"] = measure(mode_log, "mode_supply")
        log.write_text("".join(f"{name} = {value:.12g}\n" for name, value in values.items()))
        print(log)
        raise SystemExit(result)
    if args.reverse:
        text = text.replace(
            "VSEL ui_in[0] 0 pwl(0 0 25u 0 25.01u {VDDVAL} 50u {VDDVAL})",
            "VSEL ui_in[0] 0 pwl(0 {VDDVAL} 25u {VDDVAL} 25.01u 0 50u 0)",
        )
        text = text.replace(
            MEASURE_BLOCK,
            ".measure tran null_rms rms v(filtered) from=15u to=25u\n"
            ".measure tran sum_rms rms v(filtered) from=40u to=50u\n"
            ".measure tran null_cm avg v(common_mode) from=15u to=25u\n"
            ".measure tran sum_cm avg v(common_mode) from=40u to=50u\n"
            ".measure tran null_supply avg i(VDD) from=15u to=25u\n"
            ".measure tran sum_supply avg i(VDD) from=40u to=50u",
        )
    if args.select is not None:
        value = "0" if args.select == "0" else "{VDDVAL}"
        text = re.sub(
            r"^VSEL ui_in\[0\].*$",
            f"VSEL ui_in[0] 0 {value}",
            text,
            flags=re.MULTILINE,
        )
    deck.write_text(text)
    result = run_deck(args.ngspice, deck, log)
    print(log)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
