# Minimal SKY130 HD phase-selector cells

This directory is populated by `v2/tools/fetch_phase_cells.py` from
`google/skywater-pdk-libs-sky130_fd_sc_hd` at commit
`ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1`.

Only `mux2_1`, `and2_1`, `buf_4`, `inv_1`, the well-tap cell, and the upstream license
are included.  The fetcher verifies the immutable Git blob hash of every
asset.  These cells implement each local four-phase selector; the full
216 MB standard-cell repository is intentionally not vendored.
