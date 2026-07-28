# Frozen V3 shared-controller power integration

This is the immutable checkpoint after adding the centralized controller's
1.8 V `VDPWR` and `VGND` network to the exact frozen four-channel analog and
305-net signal-routed design. The only valid downstream source is
`v3_four_channel_ctrl_powered.gds` with SHA-256
`b9d4c6d085f919b4da99c9e12c09d625e40ea10d5a49625d8e745bdc7dc2daa6`.

The power network uses all 18 standard-cell row-boundary M1 rails. Every rail
has two redundant M1-to-M4 contacts at x=215.66 um and x=285.02 um, limiting
the nominal narrow-M1 path to 34.68 um. VDPWR is collected on the controller's
right edge. VGND is collected on the left edge and uses nine reviewed M3
underpasses where its row fingers cross the frozen vertical VDPWR M4 spine.
Metal 5 is unused.

The exact assembled GDS closes these gates:

- one connected VDPWR overlay and one connected VGND overlay;
- no orphan vias, floating overlay nodes, or supply-to-supply short;
- all 305 signal labels remain distinct and none is shorted to a supply;
- exactly 6037 extracted devices: 1315 analog plus 4722 digital;
- zero Magic DRC and GDS-import feedback;
- zero FEOL, BEOL, off-grid, zero-area, pin-purpose, and project flat-rule
  markers with pinned TinyTapeout support-tools commit
  `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`;
- nine extraction warnings byte-identical to the frozen analog baseline.

The row fingers are 0.60 um wide. The initial 0.80 um trial came within
0.28 um of an inherited VGND M4 trunk and was rejected before freezing. The
generator also proves that both supply labels land on their own conductor;
this prevents a legal-looking but unlabeled power component from passing the
local geometry audit.

Review images use cyan for M1, blue for M2, orange for M3, purple for M4, and
bright cut markers for the intervening vias. `02` shows the two distributed
contact columns, `03` the split left VGND spine, `04` the M3 VGND underpasses
beneath the vertical VDPWR M4 spine, and `05` the right VDPWR collection spine.

External signal handoffs and the four matched analog-input pad escapes are not
part of this checkpoint. They must be added hierarchically without modifying
the GDS frozen here.
