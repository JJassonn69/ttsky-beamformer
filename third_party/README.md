# External model data

Only the primitive SKY130 device model library is required for the current
transistor-level simulations. It is intentionally not copied into this
repository.

Pinned source:

- repository: `https://github.com/google/skywater-pdk-libs-sky130_fd_pr.git`
- commit: `f62031a1be9aefe902d6d54cddd6f59b57627436`

Recreate it from the repository root with:

```sh
git clone --depth 1 --filter=blob:none --no-checkout \
  https://github.com/google/skywater-pdk-libs-sky130_fd_pr.git \
  third_party/sky130_fd_pr
git -C third_party/sky130_fd_pr sparse-checkout init --cone
git -C third_party/sky130_fd_pr sparse-checkout set \
  cells/cap_mim_m3 cells/nfet_01v8 cells/pfet_01v8 \
  cells/res_generic_nd cells/res_generic_pd cells/res_high_po \
  cells/res_xhigh_po models/parameters models/parasitics models/r+c
git -C third_party/sky130_fd_pr checkout \
  f62031a1be9aefe902d6d54cddd6f59b57627436
```

This sparse checkout occupies about 137 MB instead of approximately 782 MB
for the full primitive repository working tree.

This is simulation model data only. Physical generation uses the separately
pinned open_pdks SKY130A installation recorded in `submission/template.lock`.
