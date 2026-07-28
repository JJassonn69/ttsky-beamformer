# Frozen V3 one-channel macro

This directory contains the only V3 GDS approved as an input to the four-channel floorplan.

- Top cell: `v3_channel_selector_late_promotion`
- GDS SHA-256: `4cd2d39ba041ac80391516b35140ce79e476117fd4e73ae22795c565befbd274`
- Extracted flat-SPICE SHA-256: `5bf0cccffad9550f06939c0cda27fb64de0bed0ccb60e102750652d78b491451`
- Magic DRC: zero markers
- Pinned Tiny Tapeout FEOL, BEOL, off-grid, zero-area, pin-purpose, and project-flat checks: zero markers
- Extracted topology: 323 devices, all eight selector/tree joins correct, 21 ports promoted, no floating wells or supply islands
- Worst conservative integrated distributed-RC edge bound: 58.5343 ps

Do not edit the frozen GDS. Any change creates a new candidate and requires a new hash plus complete topology, direct-GDS, and distributed-RC evidence. Use `python3 v3/tools/assert_current_channel.py` before floorplanning or composition.

The final signoff summaries live in:

- `v3/evidence/channel_selector_late_promotion_gate.json`
- `v3/evidence/channel_selector_late_promotion_rc.json`

