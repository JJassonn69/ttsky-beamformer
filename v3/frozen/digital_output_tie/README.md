# Frozen V3 digital-output tie-low stage

This checkpoint makes the logical constant-zero outputs real in silicon. The
only valid downstream source is `v3_four_channel_output_tied.gds`, SHA-256
`03702735a7ab4f939bc0593a5e797569bd090f682655ba882bee55488a2fcc05`.

All eight `uo_out`, all eight `uio_out`, and all eight `uio_oe` pins join one
straight Metal-4 bus connected directly to the existing `VGND` strap. Each
pin has one 0.30 um-wide direct drop. The route uses no via, no layer change,
and no meander. This is especially important for `uio_oe[7:0]`: a physical
low keeps every bidirectional pin in input mode, matching `src/project.v`.

The upper-left corridor was empty except for the existing power and ground
straps. The bus ends 2.46 um before the nearest input pin. Exact-GDS Magic
extraction proves all 24 output labels share the `VGND` network, `VDPWR`
remains separate, all 309 existing signal groups retain their prior partition,
and all 6,037 devices remain unchanged. Magic DRC and every pinned direct-GDS
geometry check report zero markers.

`01_integrated_output_ties.png` shows the tie over the complete top corridor,
`02` isolates the added conductor, and `03` enlarges the exact output-pin
drops. The final packager may add the official pin-purpose shapes and names,
but it may not regenerate or edit this electrical geometry.
