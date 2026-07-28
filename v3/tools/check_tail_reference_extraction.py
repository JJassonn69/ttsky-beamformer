#!/usr/bin/env python3
"""Prove the flattened tail reference is fully diode-connected after extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "v3" / "layout" / "bias_distribution.json"
DEFAULT_SPICE = ROOT / "build" / "v3" / "tail_reference_pilot" / "v3_tail_reference_pilot_flat.spice"
DEFAULT_GDS = ROOT / "build" / "v3" / "tail_reference_pilot" / "v3_tail_reference_pilot.gds"
DEFAULT_REPORT = ROOT / "build" / "v3" / "tail_reference_pilot" / "topology_audit.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_devices(path: Path) -> list[dict[str, object]]:
    devices = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("X"):
            continue
        fields = line.split()
        model_index = next(
            (index for index, field in enumerate(fields) if field.startswith("sky130_fd_pr__")),
            None,
        )
        if model_index is None:
            raise ValueError(f"extracted device has no SKY130 model: {line}")
        parameters = dict(
            field.split("=", 1) for field in fields[model_index + 1 :] if "=" in field
        )
        devices.append({
            "name": fields[0],
            "nets": fields[1:model_index],
            "model": fields[model_index],
            "parameters": parameters,
            "line": line,
        })
    return devices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--spice", type=Path, default=DEFAULT_SPICE)
    parser.add_argument("--gds", type=Path, default=DEFAULT_GDS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = data["reference"]["required_extracted_device_signature"]
    devices = parse_devices(args.spice)
    errors = []
    if len(devices) != expected["count"]:
        errors.append(f"expected {expected['count']} extracted fingers, found {len(devices)}")
    for device in devices:
        nets = device["nets"]
        parameters = device["parameters"]
        if len(nets) != 4:
            errors.append(f"{device['name']} has {len(nets)} terminals")
            continue
        drain, gate, source, body = nets
        if {drain, source} != set(expected["diffusions"]):
            errors.append(f"{device['name']} diffusion nets are {drain}/{source}")
        if gate != expected["gate"]:
            errors.append(f"{device['name']} gate is {gate}")
        if body != expected["body"]:
            errors.append(f"{device['name']} body is {body}")
        if device["model"] != expected["model"]:
            errors.append(f"{device['name']} model changed to {device['model']}")
        if abs(float(parameters.get("w", "nan")) - expected["finger_width_um"]) > 1e-9:
            errors.append(f"{device['name']} width changed")
        if abs(float(parameters.get("l", "nan")) - expected["length_um"]) > 1e-9:
            errors.append(f"{device['name']} length changed")
    report = {
        "schema_version": 1,
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "extracted_fingers": len(devices),
        "required_topology": "every finger has D/G=vbias_ref and S/B=VGND, allowing extracted D/S orientation exchange",
        "spice": str(args.spice.relative_to(ROOT)),
        "gds": str(args.gds.relative_to(ROOT)),
        "sha256": {
            "manifest": sha256(args.manifest),
            "spice": sha256(args.spice),
            "gds": sha256(args.gds),
            "auditor": sha256(Path(__file__)),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        for device in devices:
            print(device["line"])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
