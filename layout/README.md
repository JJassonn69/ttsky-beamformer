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
   matched breakouts and a full MIM-capacitor keep-out.
4. `tools/check_generated_routes.py` rejects cross-net same-layer overlaps
   before Magic is run.
5. `layout/extract.tcl` requires zero DRC errors and writes full-parasitic and
   topology-only extracted SPICE views.
6. `tools/check_extracted_layout.py` checks device/finger/passive counts,
   power connectivity, and unexpected net equivalences.
7. `layout/signoff.tcl` requires zero final DRC errors, emits uncompressed
   GDSII, and rejects any Magic GDS-writer geometry feedback.
8. `tools/generate_submission_lef.py` creates the exact template-pin abstract
   LEF. Magic's generic LEF output is intentionally not used because it exposes
   internal connected geometry as extra port rectangles.
9. `tools/render_gds.py` parses the emitted hierarchical GDSII directly and
   regenerates the overview, matching-core, and MIM/via detail images.

Run a physical script with the pinned SKY130 PDK and Magic:

```sh
PDK_ROOT=/path/to/pdk \
MAGIC_BIN=/path/to/magic \
tools/run_magic_layout.sh layout/pdk_smoke.tcl
```

The release tool, PDK, template, action, and output hashes are recorded in
`submission/template.lock`.
