# Minimal SKY130 HVT PMOS model closure

This directory is populated by `v2/tools/fetch_phase_cells.py` from
`google/skywater-pdk-libs-sky130_fd_pr` at commit
`f62031a1be9aefe902d6d54cddd6f59b57627436`.

It contains only the TT/FF/SS/FS/SF corner models and mismatch parameters for
`sky130_fd_pr__pfet_01v8_hvt`, which is used internally by the selected
official SKY130 HD phase-selector cells.  Git blob hashes are verified during
fetch.
