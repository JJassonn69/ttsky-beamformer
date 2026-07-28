# Frozen V3 shared-controller signal routing

This directory is the immutable checkpoint after fixed placement and routing
of all 305 internal signal nets in the centralized four-channel controller.
It is the only valid source for the controller-power stage.

The routed top is `v3_four_channel_ctrl_sig_routed`.  Its GDS SHA-256 is
`24e315ea6ae5ecdce17dc99291184bd45675daf3a5b03b42918acfcf504bd187`.
The corresponding flat extracted SPICE SHA-256 is
`10c142119818a8b3d8ec7879eb1c8bb7b6c55d0d83e93159b8d16c087840353d`.

The checkpoint closes the following gates:

- OpenROAD detailed routing: 305/305 nets, zero violations, zero inaccessible
  standard-cell pins, no signal routing above Metal 3.
- Route-graph audit: every net is one connected loop-free tree, with no dead
  leaves or missed foundry-LEF pin shapes.
- Frozen-geometry awareness: a pre-existing Metal 3 ground spine at
  `[267.22, 171.36, 268.42, 208.60]` is an explicit router obstruction.
- Power-before-signal awareness: two M2/M3 power landings at x=215.66 um and
  x=285.02 um are reserved on every one of the 18 row-boundary rails.  This
  bounds the nominal M1 distance to the nearest contact to 34.68 um instead of
  leaving the controller edge-fed through more than 100 um of narrow M1.
- Nine Metal 3 underpass corridors are also reserved so every VGND row finger
  can cross the frozen vertical VDPWR Metal 4 spine without a same-layer
  contact.
- Direct-GDS checks: zero FEOL, BEOL, off-grid, zero-area, pin-purpose, and
  project flat-rule markers using pinned `tt-support-tools` commit
  `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`.
- Full-chip Magic readback: zero DRC and GDS-import feedback; exactly 6037
  devices (1315 analog plus 4722 digital); all 305 route labels remain distinct
  and touch at least two extracted device terminals.
- The nine extraction warnings are byte-identical to the already-qualified
  frozen analog baseline; the controller adds no warning.

The empty `detailed_route_drc.rpt` is intentional and means zero detailed-route
markers.  `05_m3_frozen_trunk_detour_closeup.png` shows the affected region:
controller signals drop to Metal 2 to cross the frozen Metal 3 spine and then
return to Metal 3 without electrical contact.

Power routing and external top-level handoffs are deliberately absent.  They
are separate physical gates and must build from the hash-locked GDS here.
