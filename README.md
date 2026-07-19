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
- 47 placed SKY130 devices: 39 MOSFETs, seven PDK resistors, and one MIM
  capacitor;
- 239 extracted MOS fingers and eight extracted passives;
- deterministic M2/M3/M4 routing with 26 named tracks;
- real, uncompressed GDSII and an exact TinyTapeout-pin LEF;
- Magic placement, routed, extraction, and final DRC counts: zero;
- Magic GDS writer geometry-feedback count: zero;
- extracted nominal result: 14.705 mVrms constructive output, 42.56 dB null,
  1.539 V output common mode, and approximately 298 uA core current;
- full parasitic-extracted PVT result: 45/45 cases passed, with a 29.09 dB
  worst-case null against the 20 dB release requirement; and
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
make layout-pvt
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
```

Set `PDK_ROOT` to the directory containing `sky130A` and `MAGIC_BIN` if Magic
is not on `PATH`. The release files are
`gds/tt_um_jjassonn69_beamformer.gds` and
`lef/tt_um_jjassonn69_beamformer.lef`.

The GitHub `gds` workflow uses TinyTapeout's pinned `ttsky26c` custom-GDS and
precheck actions. A green precheck confirms submission compatibility, not
manufacturing yield; the remaining electrical risks and bench plan are kept
explicit in `docs/presilicon_plan.md`.

## Fabrication layout

![KLayout rendering of the final beamformer GDS](docs/images/beamformer-gds.png)

This is a mask-layer rendering of the exact committed GDSII stream, not a
post-fabrication microscope photograph. The image can be regenerated from the
GDS with KLayout and the pinned SKY130A layer-properties file.
