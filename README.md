# Tiny Tapeout four-channel vector beamformer

[![gds](../../actions/workflows/gds.yaml/badge.svg)](../../actions/workflows/gds.yaml)
[![docs](../../actions/workflows/docs.yaml/badge.svg)](../../actions/workflows/docs.yaml)

The active V3 submission is a four-channel, receive-only, constant-`gm`
Cartesian vector beamformer for the SKY130 Tiny Tapeout analog flow. Four
coherent 5 MHz low-IF inputs receive independently programmable phase/amplitude
weights and sum into one differential 1 MHz output. A nominal 16 MHz master
clock creates four 4 MHz quadrature switching phases on chip.

Each channel contains 15 equal transconductor/mixer slices in binary groups of
1, 2, 4, and 8. Every group stays active and selects I+, Q+, I-, or Q-. This
keeps total channel transconductance nearly constant while exposing 256 raw
vector words per channel. Eight automatic beam settings are also provided.

The ports are high-impedance low-IF ports, not 50-ohm RF ports. A 10.5 GHz
system therefore needs four coherent external RF-to-IF paths; the chip performs
beamforming after downconversion.

The detailed [V3 engineering datasheet](v3/docs/datasheet.md),
[architecture contract](v3/spec/beamformer_v3.md), and
[physical-design record](v3/README.md) are the authoritative documents.

## Active submission artifacts

- Tiny Tapeout allocation: 2x2 tiles, 334.88 x 225.76 um.
- Power: `VDPWR`/`VGND` at 1.8 V; `VAPWR` is not used.
- Analog pins: `ua[0:3]` element inputs and `ua[4:5]` differential output.
- Digital control: three beam-select bits, raw-vector mode, four channel
  enables, and a three-wire 32-bit serial configuration interface.
- Tiny Tapeout wrapper: `gds/tt_um_jjassonn69_beamformer.gds`.
- Frozen internal-signoff copy:
  `v3/frozen/submission/tt_um_jjassonn69_beamformer.gds`.
- Frozen GDS SHA-256:
  `824e38f94ce4fbff84d0c079dcb059d6944bca7569a0f657134c318f31553c14`.

The wrapper is generated deterministically from the frozen physical top. It
adds the exact Tiny Tapeout pins, labels, and full project boundary while
preserving the previously extracted electrical geometry.

## Current validation state

The exact candidate passes the consolidated internal signoff gate. The frozen
evidence includes:

- zero pinned FEOL, BEOL, off-grid, zero-area, pin-purpose, project-flat, and
  Magic DRC markers;
- independent flattened extraction of 6,037 devices and all used/unused pin
  connectivity;
- eight architecture states and all 256 raw words per channel;
- five-corner PVT and 16 independently calibrated mismatch realizations;
- bounded compression, output-loading, spur/noise-equivalent, and all 56
  ordered code-transition tests;
- distributed metal-RC matching on all four inputs and both outputs; and
- an eight-case power-on matrix with a required 60 us post-supply wait.

This remains a research prototype, not a production-qualified radio. Native
PSS/PNoise, foundry-qualified yield, package/board behavior, RF-front-end
matching, and measured beam patterns remain explicit system/silicon tasks.
The official Tiny Tapeout custom-GDS, viewer, precheck, and artifact-bound
validation jobs are green on the exact frozen hash. Human visual review is the
remaining step before fabrication submission; any geometry edit invalidates
the hash-bound evidence.

## Reproduce the release checks

```sh
make submission-artifacts
make test
make release-check
```

These targets fetch the pinned Tiny Tapeout 2x2 template, regenerate the V3
wrapper/LEF, require byte equality with the frozen artifact, run the complete
V3 regression and flattened upper-metal interaction rules, and rebuild the
consolidated submission gate.

## Repository history

V2 and the original two-channel experiment remain in the repository as frozen
engineering history and reusable, tested implementation machinery. They are
not the active submission. Intentional V2 references inside V3 generators are
documented reuse of the proven template, device, or controller tooling—not a
claim that V2 is current.
