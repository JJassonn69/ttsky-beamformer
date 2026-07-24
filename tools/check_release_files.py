#!/usr/bin/env python3
"""Run the active V2 artifact and evidence integrity checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> None:
    run("-m", "unittest", "v2.tests.test_submission_artifacts", "-v")
    run("v2/tools/check_latest_validation.py")


if __name__ == "__main__":
    main()
