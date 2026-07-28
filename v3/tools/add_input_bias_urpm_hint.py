#!/usr/bin/env python3
"""Add the direct-deck URPM width hint around the 0.35 um bias resistor."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "v3" / "channel_input_bias_pilot"
MANIFEST = ROOT / "v3" / "layout" / "compact_input_bias_placement.json"
DEFAULT_INPUT = BUILD / "v3_channel_input_bias_pilot_magic.gds"
DEFAULT_OUTPUT = BUILD / "v3_channel_input_bias_pilot.gds"
DEFAULT_KLAYOUT = Path("/Applications/KLayout/klayout.app/Contents/MacOS/klayout")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--klayout", type=Path, default=DEFAULT_KLAYOUT)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bbox = manifest["urpm_width_repair"]["bbox"]
    # Pilot geometry is translated by (20,20) um by the exact channel generator.
    absolute = [bbox[0] + 20.0, bbox[1] + 20.0, bbox[2] + 20.0, bbox[3] + 20.0]
    with tempfile.TemporaryDirectory(prefix="v3-urpm-") as temp:
        script = Path(temp) / "add_urpm.py"
        script.write_text(
            "import pya\n"
            f"layout=pya.Layout(); layout.read({str(args.input.resolve())!r})\n"
            "top=layout.top_cell(); layer=layout.layer(79,20)\n"
            f"box=pya.DBox({absolute[0]}, {absolute[1]}, {absolute[2]}, {absolute[3]})\n"
            "top.shapes(layer).insert(box)\n"
            f"layout.write({str(args.output.resolve())!r})\n",
            encoding="utf-8",
        )
        result = subprocess.run([str(args.klayout), "-b", "-r", str(script)], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)
    evidence = {
        "schema_version": 1,
        "status": "pass",
        "scope": "mask-only URPM 79/20 minimum-width repair; no conductor, poly, device, via, or label geometry changed",
        "input": str(args.input.relative_to(ROOT)),
        "input_sha256": sha256(args.input),
        "output": str(args.output.relative_to(ROOT)),
        "output_sha256": sha256(args.output),
        "urpm_bbox_local_um": bbox,
        "urpm_bbox_pilot_um": absolute,
        "manifest_sha256": sha256(MANIFEST),
        "klayout_sha256": sha256(args.klayout),
    }
    path = ROOT / "v3" / "evidence" / "input_bias_urpm_repair.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
