"""Capture small, deterministic solver/platform provenance for JSON reports."""

from __future__ import annotations

import platform
import re
import subprocess


def ngspice_provenance(executable: str) -> dict[str, str]:
    completed = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    text = completed.stdout + completed.stderr
    match = re.search(r"ngspice-([0-9.]+)", text)
    if completed.returncode or match is None:
        raise SystemExit(f"cannot identify ngspice solver: {executable}")
    return {
        "ngspice_version": match.group(1),
        "platform": platform.platform(),
    }
