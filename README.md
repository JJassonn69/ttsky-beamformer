# Tiny Tapeout Beamformer

[![gds](../../actions/workflows/gds.yaml/badge.svg)](../../actions/workflows/gds.yaml)
[![docs](../../actions/workflows/docs.yaml/badge.svg)](../../actions/workflows/docs.yaml)

A deliberately small two-channel low-IF beamformer for the SKY130 Tiny
Tapeout analog flow. Two phase-coherent 5 MHz inputs are commutated by an
on-chip 4 MHz complementary LO and summed into a differential 1 MHz output.
`ui_in[0]` selects a 0- or 180-degree channel-two weight.

This first silicon iteration intentionally leaves impedance matching, the LNA,
RF phase shifting, and the output filter off-chip. The analog inputs are
high-impedance, AC-coupled IF inputs; they are not 50-ohm RF ports.

The detailed [engineering datasheet and iteration handoff](docs/datasheet.md)
records the architecture, pin behavior, results, physical flow, bench plan,
known risks, and recommended iteration-two roadmap.

## Release-candidate implementation

- official 1x2 analog boundary: 161.00 x 225.76 um;
- 70 placed SKY130 devices: 62 MOSFET PCells, seven PDK resistors, and one MIM
  capacitor;
- 338 extracted MOS fingers and eight extracted passives;
- channel devices split into an A/B; B/A common-centroid pattern, with mirrored
  passives and matched local breakouts;
- deterministic M2/M3/M4 routing with 30 named tracks and explicit MIM
  routing keep-outs;
- real, uncompressed GDSII and an exact TinyTapeout-pin LEF;
- Magic placement, routed, extraction, and final DRC counts: zero;
- Magic GDS writer geometry-feedback count: zero;
- nominal extracted 1 MHz wanted-tone result: 0.809 mVrms constructive output
  and 44.60 dB null at a 4 MHz LO;
- extracted higher-clock characterization passes the 20 dB release criterion
  at 4, 10, 20, and 30 MHz, with 33.54 dB null at 30 MHz;
- full parasitic-extracted PVT passes 45/45 TT/SS/FF/SF/FS,
  1.62/1.80/1.98 V, and -40/27/125 C cases, with a 25.60 dB worst null;
- 30/30 foundry-slope mismatch-surrogate trials pass, with 39.28 dB worst-case
  null; and
- all locally runnable checks from the official TinyTapeout precheck pass,
  including exact DEF/LEF/GDS pin geometry, analog-pad connectivity, boundary,
  layers, power ports, cell names, and Verilog syntax.

The analog core is always active while `VDPWR` is present. `ena` and `rst_n`
are boundary-compatible reserved inputs in this minimal revision; shutdown,
gain control, and multi-bit phase weights are planned for later iterations.

## Reproduce electrical verification

The behavioral and SPICE regressions require Python, ngspice, and the sparse
pinned SKY130 model checkout described in `third_party/README.md`.

```sh
make verify
make pvt
make layout-sim
make layout-balance
make layout-clock-sweep
make layout-frequency-sweep
make layout-pvt
make mismatch-mc
```

The full deterministic PVT grid is five process corners, three supplies
(1.62/1.80/1.98 V), and three temperatures (-40/27/125 C). Generated logs and
JSON reports are written below `build/`.

## Reproduce physical signoff

The layout flow uses the exact TinyTapeout DEF, SKY130 PCells, Magic 8.3.676,
and the precheck PDK revision recorded in `submission/template.lock`.

```sh
make layout-scripts
make layout-place
make layout-route
make layout-extract
make layout-signoff
make submission-evidence
make release-check
```

Set `PDK_ROOT` to the directory containing `sky130A` and `MAGIC_BIN` if Magic
is not on `PATH`. The release files are
`gds/tt_um_jjassonn69_beamformer.gds` and
`lef/tt_um_jjassonn69_beamformer.lef`.

The GitHub `gds` workflow uses TinyTapeout's pinned `ttsky26c` custom-GDS and
precheck actions. Before invoking them it also flattens the exact release GDS
and rejects M3/M4 spacing, M4 width/connected-area, and capm-clearance regressions;
the same gate runs from `make verify`, `make layout-signoff`, and
`make release-check`. A green precheck confirms submission compatibility, not
manufacturing yield; the remaining electrical risks and bench plan are kept
explicit in `docs/presilicon_plan.md`.

## Fabrication layout

![Signed-off GDS layer rendering of the final beamformer](docs/images/beamformer-gds.png)

This is a mask-layer rendering of the exact committed GDSII stream, not a
post-fabrication microscope photograph. It can be regenerated directly from
the release GDS with `tools/render_gds.py`; detailed core and capacitor views
are included in the engineering datasheet.
