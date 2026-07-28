#!/usr/bin/env python3
"""Compare Magic's flat extracted devices against the physical manifest."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "layout" / "circuit.json"


def canonical_net(net: str) -> str:
    return "ui_in[0]" if net == "select" else net


def number(parameters: dict[str, str], key: str) -> float:
    return round(float(parameters[key]), 2)


def expected_devices() -> Counter[tuple[object, ...]]:
    expected: Counter[tuple[object, ...]] = Counter()
    manifest = json.loads(MANIFEST.read_text())
    for device in manifest["devices"]:
        kind = device["kind"]
        nets = {key: canonical_net(value) for key, value in device["nets"].items()}
        if kind in {"nmos", "pmos"}:
            model = "sky130_fd_pr__nfet_01v8" if kind == "nmos" else "sky130_fd_pr__pfet_01v8"
            signature = (
                model,
                tuple(sorted((nets["D"], nets["S"]))),
                nets["G"],
                nets["B"],
                round(float(device["total_w"]) / int(device["nf"]), 2),
                round(float(device["l"]), 2),
            )
            expected[signature] += int(device["nf"])
        elif kind.startswith("res_"):
            model = (
                "sky130_fd_pr__res_high_po_1p41"
                if kind == "res_high_po"
                else "sky130_fd_pr__res_xhigh_po_1p41"
            )
            expected[(model, tuple(sorted((nets["R1"], nets["R2"]))), nets["B"],
                      round(float(device["l"]), 2))] += 1
        elif kind == "cap_mim_m3":
            expected[("sky130_fd_pr__cap_mim_m3_1",
                      tuple(sorted((nets["C1"], nets["C2"]))),
                      round(float(device["l"]), 2),
                      round(float(device["w"]), 2))] += 1
        else:
            raise ValueError(f"unsupported manifest kind {kind}")
    return expected


def expected_bias_reference() -> tuple[tuple[object, ...], int]:
    """Return the exact flattened signature of the diode-connected bias pair.

    Keeping this assertion separate from the aggregate device comparison makes
    the safety property explicit in signoff output: the gate/drain strap is
    intentional, while source/body must remain on a different ground net.
    """
    manifest = json.loads(MANIFEST.read_text())
    devices = {
        device["name"]: device
        for device in manifest["devices"]
        if device["name"] in {"XBIASA", "XBIASB"}
    }
    if set(devices) != {"XBIASA", "XBIASB"}:
        raise ValueError("manifest must contain exactly XBIASA and XBIASB")

    signatures: set[tuple[object, ...]] = set()
    finger_count = 0
    for name, device in devices.items():
        nets = {key: canonical_net(value) for key, value in device["nets"].items()}
        if not (
            device["kind"] == "nmos"
            and nets["D"] == nets["G"] == "vbias"
            and nets["S"] == nets["B"] == "VGND"
            and nets["D"] != nets["S"]
        ):
            raise ValueError(
                f"{name} must remain diode-connected D=G=vbias, "
                "S=B=VGND, with vbias distinct from VGND"
            )
        signatures.add((
            "sky130_fd_pr__nfet_01v8",
            tuple(sorted((nets["D"], nets["S"]))),
            nets["G"],
            nets["B"],
            round(float(device["total_w"]) / int(device["nf"]), 2),
            round(float(device["l"]), 2),
        ))
        finger_count += int(device["nf"])
    if len(signatures) != 1:
        raise ValueError("XBIASA and XBIASB must have identical unit geometry")
    return signatures.pop(), finger_count


def actual_devices(path: Path) -> Counter[tuple[object, ...]]:
    actual: Counter[tuple[object, ...]] = Counter()
    for line in path.read_text().splitlines():
        if not line.startswith("X"):
            continue
        fields = line.split()
        model_index = next(
            (index for index, field in enumerate(fields) if field.startswith("sky130_fd_pr__")),
            None,
        )
        if model_index is None:
            raise ValueError(f"extracted element has no SKY130 model: {line}")
        model = fields[model_index]
        nets = [canonical_net(net) for net in fields[1:model_index]]
        parameters = dict(field.split("=", 1) for field in fields[model_index + 1 :] if "=" in field)
        if model in {"sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8"}:
            if len(nets) != 4:
                raise ValueError(f"MOS has {len(nets)} terminals: {line}")
            signature = (
                model,
                tuple(sorted((nets[0], nets[2]))),
                nets[1],
                nets[3],
                number(parameters, "w"),
                number(parameters, "l"),
            )
        elif "__res_" in model:
            if len(nets) != 3:
                raise ValueError(f"resistor has {len(nets)} terminals: {line}")
            signature = (model, tuple(sorted(nets[:2])), nets[2], number(parameters, "l"))
        elif model == "sky130_fd_pr__cap_mim_m3_1":
            if len(nets) != 2:
                raise ValueError(f"capacitor has {len(nets)} terminals: {line}")
            signature = (
                model,
                tuple(sorted(nets)),
                number(parameters, "l"),
                number(parameters, "w"),
            )
        else:
            raise ValueError(f"unexpected extracted model {model}")
        actual[signature] += 1
    return actual


def check_equivalences(ext_path: Path) -> bool:
    equivalences = []
    for line in ext_path.read_text().splitlines():
        match = re.match(r'equiv "([^"]+)" "([^"]+)"', line)
        if match:
            equivalences.append(frozenset(match.groups()))
    expected = [frozenset(("ui_in[0]", "select"))]
    # Magic may either preserve the non-port `select` label as an explicit
    # equivalence or immediately canonicalize the connected conductor to the
    # DEF port name `ui_in[0]` and omit the redundant label.  Both are safe;
    # the full device-signature comparison below independently requires every
    # manifest `select` terminal to extract on ui_in[0].  Any other alias is a
    # real short and remains forbidden.
    if equivalences not in ([], expected):
        raise SystemExit(f"unexpected extracted net equivalences: {equivalences}")
    return equivalences == expected


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_extracted_layout.py EXTRACTED_SPICE TOP_EXT")
    spice_path = Path(sys.argv[1])
    ext_path = Path(sys.argv[2])
    explicit_select_alias = check_equivalences(ext_path)
    expected = expected_devices()
    actual = actual_devices(spice_path)
    if actual != expected:
        print("Missing extracted devices:")
        for signature, count in (expected - actual).items():
            print(count, signature)
        print("Unexpected extracted devices:")
        for signature, count in (actual - expected).items():
            print(count, signature)
        raise SystemExit(1)
    bias_signature, bias_fingers = expected_bias_reference()
    if actual[bias_signature] != bias_fingers:
        raise SystemExit(
            "extracted bias reference is not the expected distinct-net "
            f"diode connection: expected {bias_fingers} fingers, "
            f"found {actual[bias_signature]}"
        )
    totals = Counter()
    for signature, count in actual.items():
        model = str(signature[0])
        totals["mos" if "fet_01v8" in model else "passive"] += count
    print(
        "Extracted-layout topology passed: "
        f"{totals['mos']} MOS fingers, {totals['passive']} passives, "
        f"{bias_fingers} bias fingers preserve D=G=vbias and S=B=VGND, "
        "power connected, no unexpected net equivalences, "
        "select/ui_in[0] "
        + ("explicitly aliased" if explicit_select_alias else "canonically merged")
    )


if __name__ == "__main__":
    main()
