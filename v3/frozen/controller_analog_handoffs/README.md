# Frozen V3 controller-to-analog handoffs

This checkpoint adds the 41 internal handoff nets between the powered
centralized controller and the four-channel analog array. The only valid
downstream source is `v3_four_channel_ctrl_analog_handoffs.gds` with SHA-256
`1c249b3a49c0852d278a4ef6f52a3304146eee10e220aa80ef15c83865f263b7`.

The handoffs contain four shared phase outputs, 32 per-channel group-code
signals, four channel-bias enables, and one four-way mixer-blanking tree. They
were detailed-routed on M2--M4 against an exact obstruction map of the frozen
source. M5 is unused. The independent route-graph audit proves 85 endpoint
attachments, no floating leaves, and no loops.

The exact assembled GDS closes these gates:

- 41 extracted handoff groups, each joined to exactly its intended controller
  route and no other controller net;
- 305 distinct controller routes and zero signal-to-supply shorts;
- every phase reaches 32 selector terminals across all four channels;
- every group, enable, and blanking handoff reaches only its declared selector
  endpoint or endpoints;
- unchanged 6,037-device and supply-terminal populations;
- zero OpenROAD final violations and zero Magic DRC/import feedback;
- zero FEOL, BEOL, off-grid, zero-area, pin-purpose, and project flat-rule
  markers using pinned TinyTapeout support-tools commit
  `d65690eeb1d4afd26aef795c805a23d9d9daf9d1`;
- nine extraction warnings byte-identical to the frozen analog baseline.

The four phase-tree landing extensions are deliberate and identical. Each is
0.30 um long with the same line-end halo. They replace a first legal-looking
candidate that produced three foundry M4 line-end markers. Signal-via landing
dimensions also use the exact M2/M3 and M3/M4 signal rules, rather than the
larger power-contact geometry.

The standalone route view is `02_handoff_overlay_only.png`; `03` isolates the
four phase handoffs, `04` the 32 group-code routes, and `05` the enable and
blanking routes. Static control wiring looks dense because 37 independent
signals cross a narrow region, but the extracted and graph-based audits prove
that none of the visible crossings creates an electrical connection.

TinyTapeout external digital inputs and the four matched analog-input pad
escapes are not part of this checkpoint. They must be added hierarchically
without modifying the frozen GDS here.
