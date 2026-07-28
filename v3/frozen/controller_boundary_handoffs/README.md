# Frozen V3 controller-to-TinyTapeout boundary handoffs

This checkpoint routes all 14 controller inputs to the exact TinyTapeout 2x2
digital-interface rectangles. The only valid downstream source is
`v3_four_channel_ctrl_boundary_handoffs.gds`, SHA-256
`598790c7ed1358cdff93a05393aed9e245238a6712e1242d69516215c3bdc452`.

The boundary mapping is `clk`, `rst_n`, and `ena`; `beam_select[2:0]` on
`ui_in[2:0]`; `raw_mode` on `ui_in[3]`; four channel enables on
`ui_in[7:4]`; and `cfg_clk`, `cfg_data`, and `cfg_latch` on `uio_in[2:0]`.
The routes use M2--M4 and no M5.

The independent route-graph audit proves 28 endpoint attachments, zero missed
pins, zero floating leaves, and zero loops. Exact-GDS Magic extraction proves
14 distinct boundary nets, each joined to its one intended controller route,
with no connection to either supply or any of the 41 internal analog
handoffs. All 305 controller routes and all 6,037 devices remain unchanged.

The checkpoint reproduces the 14 official terminal rectangles rather than
waiting for a later wrapper to add their metal. That closes the local M4 area
rules now and makes the next hierarchy unambiguous. Pinned TinyTapeout FEOL,
BEOL, off-grid, zero-area, pin-purpose, project-flat, and Magic DRC checks all
report zero markers.

`01_integrated_boundary_handoffs.png` shows the routes over the complete
design. `02_boundary_overlay_only.png` isolates the new wiring, `03` shows the
exact TinyTapeout terminal landings, and `04` shows the controller landings.

The four analog input escapes are not part of this checkpoint. They must be
added as a matched four-route structure by attaching this GDS hierarchically;
the frozen geometry here may not be regenerated or edited.
