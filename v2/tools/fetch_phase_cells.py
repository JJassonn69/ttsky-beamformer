#!/usr/bin/env python3
"""Fetch the minimal pinned SKY130 HD cells used by the V2 phase selectors."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESTINATION = PROJECT_ROOT / "third_party" / "sky130_fd_sc_hd_cells"
HVT_DESTINATION = PROJECT_ROOT / "third_party" / "sky130_fd_pr_hvt"
REPOSITORY = "google/skywater-pdk-libs-sky130_fd_sc_hd"
COMMIT = "ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1"
HVT_REPOSITORY = "google/skywater-pdk-libs-sky130_fd_pr"
HVT_COMMIT = "f62031a1be9aefe902d6d54cddd6f59b57627436"

ASSETS = {
    "LICENSE": ("LICENSE", "d645695673349e3947e8e5ae42332d0ac3164cd7"),
    "sky130_fd_sc_hd__mux2_1.gds": ("cells/mux2/sky130_fd_sc_hd__mux2_1.gds", "8c52c6cc5f9d90f63028798d25d622e3934265a4"),
    "sky130_fd_sc_hd__mux2_1.lef": ("cells/mux2/sky130_fd_sc_hd__mux2_1.lef", "75207c060e2dac2c0777b898a8a7fad5c777d28c"),
    "sky130_fd_sc_hd__mux2_1.spice": ("cells/mux2/sky130_fd_sc_hd__mux2_1.spice", "4e01075e8f858c523db7390fa255e8aed0f8f521"),
    "sky130_fd_sc_hd__and2_1.gds": ("cells/and2/sky130_fd_sc_hd__and2_1.gds", "e39afde12d56cbb70d616e2e59d35d0a4a0405cd"),
    "sky130_fd_sc_hd__and2_1.lef": ("cells/and2/sky130_fd_sc_hd__and2_1.lef", "5abf91694ffcdf66d280e2dd82218312b38e43ac"),
    "sky130_fd_sc_hd__and2_1.spice": ("cells/and2/sky130_fd_sc_hd__and2_1.spice", "e7529bcc851caf661bd47415774c57788ab623ee"),
    "sky130_fd_sc_hd__buf_4.gds": ("cells/buf/sky130_fd_sc_hd__buf_4.gds", "da41f9ca377c9203629a54a4a1a05433bdbbcaf1"),
    "sky130_fd_sc_hd__buf_4.lef": ("cells/buf/sky130_fd_sc_hd__buf_4.lef", "614ccd17b46bd95601d778b95e3d6ae296a78fc1"),
    "sky130_fd_sc_hd__buf_4.spice": ("cells/buf/sky130_fd_sc_hd__buf_4.spice", "6bf9c6c13c7d111520a4c50922f8eac21821d0ee"),
    "sky130_fd_sc_hd__inv_1.gds": ("cells/inv/sky130_fd_sc_hd__inv_1.gds", "82fa94b6a670b2660ae29ba89c38ab7bb2529245"),
    "sky130_fd_sc_hd__inv_1.lef": ("cells/inv/sky130_fd_sc_hd__inv_1.lef", "79703b337be3ffa34b27160f32ff4131a8938762"),
    "sky130_fd_sc_hd__inv_1.spice": ("cells/inv/sky130_fd_sc_hd__inv_1.spice", "97f46d97e149159f705f09317dc5f948e332993d"),
    "sky130_fd_sc_hd__tapvpwrvgnd_1.gds": ("cells/tapvpwrvgnd/sky130_fd_sc_hd__tapvpwrvgnd_1.gds", "0706b528504c0d3ebc74fad76b4ab2e3ecbed678"),
    "sky130_fd_sc_hd__tapvpwrvgnd_1.lef": ("cells/tapvpwrvgnd/sky130_fd_sc_hd__tapvpwrvgnd_1.lef", "02d7c83337f46926ae330c7d0ba67017f004ef2f"),
}

HVT_ASSETS = {
    "sky130_fd_pr__pfet_01v8_hvt__tt.corner.spice": "6b0413e31482eb6719c23ba028fcd00d2b776970",
    "sky130_fd_pr__pfet_01v8_hvt__tt.pm3.spice": "e62c03c47cbff535fe64d874666101104273c198",
    "sky130_fd_pr__pfet_01v8_hvt__ff.corner.spice": "dff917e456854aa2164e9bc600e432027713584c",
    "sky130_fd_pr__pfet_01v8_hvt__ff.pm3.spice": "b786123884a021d275d5b0417f94caa2f9aa76aa",
    "sky130_fd_pr__pfet_01v8_hvt__ss.corner.spice": "f7904c7e9727ce153cdd42b9bf1311107b7595a5",
    "sky130_fd_pr__pfet_01v8_hvt__ss.pm3.spice": "75edefde7d7ec849e5bfaeb790781781a63cc32c",
    "sky130_fd_pr__pfet_01v8_hvt__fs.corner.spice": "dceea544f8da327a69acecb82ff21a1634d3e400",
    "sky130_fd_pr__pfet_01v8_hvt__fs.pm3.spice": "760e4ccc3a621b60d22d8fb0c5807dad6b67264e",
    "sky130_fd_pr__pfet_01v8_hvt__sf.corner.spice": "fa771bdb7ff7c6e8493684ad313556a2b034950d",
    "sky130_fd_pr__pfet_01v8_hvt__sf.pm3.spice": "e7b678005c7aef8d72ce94cd0d0ff8b6186a37f3",
    "sky130_fd_pr__pfet_01v8_hvt__mismatch.corner.spice": "90cbe3c5bf3c9d2d79cff8f864b1aefdf6c4f991",
}


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for destination_name, (source_path, expected_sha1) in ASSETS.items():
        destination = DESTINATION / destination_name
        if destination.exists():
            data = destination.read_bytes()
        else:
            url = (
                f"https://raw.githubusercontent.com/{REPOSITORY}/"
                f"{COMMIT}/{source_path}"
            )
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
            destination.write_bytes(data)
        actual_sha1 = git_blob_sha1(data)
        if actual_sha1 != expected_sha1:
            raise SystemExit(
                f"{destination}: Git blob SHA-1 {actual_sha1} != {expected_sha1}"
            )
        print(f"verified {destination.relative_to(PROJECT_ROOT)} {actual_sha1}")

    HVT_DESTINATION.mkdir(parents=True, exist_ok=True)
    for destination_name, expected_sha1 in HVT_ASSETS.items():
        destination = HVT_DESTINATION / destination_name
        if destination.exists():
            data = destination.read_bytes()
        else:
            source_path = f"cells/pfet_01v8_hvt/{destination_name}"
            url = (
                f"https://raw.githubusercontent.com/{HVT_REPOSITORY}/"
                f"{HVT_COMMIT}/{source_path}"
            )
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            destination.write_bytes(data)
        actual_sha1 = git_blob_sha1(data)
        if actual_sha1 != expected_sha1:
            raise SystemExit(
                f"{destination}: Git blob SHA-1 {actual_sha1} != {expected_sha1}"
            )
        print(f"verified {destination.relative_to(PROJECT_ROOT)} {actual_sha1}")


if __name__ == "__main__":
    main()
