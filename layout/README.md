# Physical layout

The production macro occupies TinyTapeout's SKY130 1x2 analog boundary
(161.00 x 225.76 um) and preserves every port from the authenticated official
DEF template.

The reproducible flow is:

1. `tools/fetch_tt_template.py` authenticates the pinned template DEF.
2. `tools/generate_layout_scripts.py` generates the Magic PCell placement for
   all 70 devices, including the split common-centroid channel units, and the
   full-height power ports.
3. `tools/generate_route_script.py` reads actual PCell terminal labels and
   generates deterministic local-M2/M3/M4 routing on 30 named tracks, with
   matched breakouts, a full MIM-capacitor keep-out, and a top-edge route
   ceiling that clears every TinyTapeout digital M4 pin by at least 0.30 um.
4. `tools/check_generated_routes.py` rejects cross-net same-layer overlaps,
   cross-net via-to-adjacent-metal overlaps, disconnected same-net conductor
   islands, and independently checks the exact top-pin rectangles before
   Magic is run.
5. `layout/extract.tcl` requires zero DRC errors and writes three explicit
   views: device/capacitance (`extracted.spice`), distributed route-RC
   (`extracted_rc.spice`), and capacitance-suppressed topology/LVS
   (`extracted_lvs.spice`). The RC view uses Magic `extract do resistance`,
   zero network/segment thresholds, no topology simplification or resistor
   pruning, and `ext2spice extresist on`.
6. `tools/check_extracted_layout.py` checks device/finger/passive counts,
   power connectivity, and unexpected net equivalences.
7. `tools/check_distributed_rc.py` rejects a capacitance-only fallback, proves
   the `.res.ext` annotation exists, checks explicit R/C/internal-node counts,
   preserves the device count, requires every manifest net to participate in
   the resistor graph, and rejects any resistor component not anchored to a
   manifest net.
8. `layout/signoff.tcl` requires zero final DRC errors, emits uncompressed
   GDSII, and rejects any Magic GDS-writer geometry feedback.
9. `tools/generate_submission_lef.py` creates the exact template-pin abstract
   LEF. Magic's generic LEF output is intentionally not used because it exposes
   internal connected geometry as extra port rectangles.
10. `tools/render_gds.py` parses the emitted hierarchical GDSII directly and
   regenerates the overview, matching-core, MIM/via, and top-pin-clearance
   detail images.

The Make dependency graph deliberately rebuilds clean placement before every
route and rebuilds routing before every extraction. Magic route paint is
additive, so this prevents two route revisions from accumulating in a stale
`build/layout/buffered` cell and turning into an extraction-only short.

Run a physical script with the pinned SKY130 PDK and Magic:

```sh
PDK_ROOT=/path/to/pdk \
MAGIC_BIN=/path/to/magic \
tools/run_magic_layout.sh layout/pdk_smoke.tcl
```

The release tool, PDK, template, action, and output hashes are recorded in
`submission/template.lock`. Numeric matching, width, via, clearance, rebuild,
and distributed-RC requirements are maintained as the physical constraint
contract in `spec/beamformer_v1.md`.
