# Frozen V3 four-channel integration checkpoint

This directory is the only approved input to the next V3 top-level physical
stage. It contains four immutable one-channel macros plus the closed
differential output collector, four phase trees, balanced REF/VBIAS trees,
the exact VCM generator, and the complete tail-bias reference/decoupling
block.

- Top cell: `v3_four_channel_shared_support_integration`
- GDS SHA-256: `165150fa12c5ba4ac5191d5c2452b9ced901104dd71d522c156feed7fe213228`
- Flat Spice SHA-256: `3390614e23ff01c9b0dd7cadcc8429dab40ff160cd3ebeaf05f7e5cdf5b5b175`
- Magic DRC: zero markers
- Direct-GDS precheck: zero FEOL, BEOL, off-grid, zero-area, pin-purpose,
  and project-flat markers
- Extracted population: 1,312 devices

Do not use a GDS from `build/v3`, a manual canvas, or an earlier four-channel
pilot as a future source. `v3/CURRENT.json` and
`v3/tools/assert_current_top.py` enforce this checkpoint.

The rejected tail-decoupling attempt is deliberately not retained as GDS. It
crossed the first MIM capacitor's bottom-plate Via-3 strip and extraction
shorted VBIAS to ground even though DRC was zero. The active generator routes
an M4 spine above the full capacitor bboxes and drops separately to both C1
terminals.
