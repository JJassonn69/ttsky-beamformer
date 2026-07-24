# Tiny Tapeout four-channel beamformer

[![gds](../../actions/workflows/gds.yaml/badge.svg)](../../actions/workflows/gds.yaml)
[![docs](../../actions/workflows/docs.yaml/badge.svg)](../../actions/workflows/docs.yaml)

This repository's active submission is a four-channel quadrature low-IF
receive beamformer for the SKY130 Tiny Tapeout analog flow. Four coherent
5 MHz element inputs are weighted by selectable 0, 90, 180, or 270 degree LO
phases and summed into one differential 1 MHz output. A nominal 16 MHz master
clock generates the four 4 MHz switching phases on chip.

The design provides four selectable beam codes, per-channel enable, manual
phase override, and four independent 4-bit switched-tail gain trims. The trim
network corrects channel-to-channel gain error; it is not used to synthesize
phase. The analog ports are high-impedance low-IF ports, not 50-ohm RF ports,
so matching and a 50-ohm output driver remain off chip.

The detailed [V2 engineering datasheet](v2/docs/datasheet.md),
[architecture contract](v2/spec/beamformer_v2.md), and
[physical-design record](v2/spec/physical_design.md) are the authoritative
design documents.

## Active submission artifacts

- Tiny Tapeout allocation: 2x2 tiles, 334.88 x 225.76 um.
- Power: `VDPWR`/`VGND` at 1.8 V; `VAPWR` is not used.
- Analog pins: `ua[0:3]` element inputs and `ua[4:5]` differential output.
- Digital control: two beam-select bits, four channel enables, manual mode,
  a reserved direction input, and a three-wire configuration interface.
- Physical candidate:
  `build/v2/control_routing/direct/v2_control_quadrature_routed.gds`, SHA-256
  `90b51a5f37fd114a8cb24afec32ba1c5364b64f15865f19fe738caa7cb8a994a`.
- Tiny Tapeout wrapper:
  `gds/tt_um_jjassonn69_beamformer.gds`, SHA-256
  `c0fe0aa6cf1fa9999c8c8e4a9804f367e8dca4371757e5e9c62f4d6e8ba6d1f2`.

The wrapper is a deterministic one-record top-cell rename. It changes no
geometry and is checked against the exact physical candidate in CI.

## Current validation state

The current candidate has zero Magic full-chip DRC errors and zero Magic GDS
import/extraction feedback. Its direct-GDS topology and route checks reject
floating via stubs, malformed cuts, missing enclosures, unintended route
islands, and signal-to-power shorts.

The selected 32-fixed-unit plus reset-code-8 tail-current architecture has
been physically regenerated and frozen. Current-hash Magic DRC, extracted
topology, complete distributed-RC coverage, cold start, 64-case trim transfer,
bounded load/amplitude/frequency/clock sensitivity, two-tone linearity, and
representative PVT endpoints pass. The final signoff campaign additionally
passes every one of 60 modeled MOS-mismatch samples and every one of the 20
distributed-RC beam/codebook cases. Worst raw codebook rejection is 61.05 dB,
constructive spread is 0.244 dB, and worst modeled-mismatch rejection is
36.53 dB. Compact local release evidence is frozen only after these reports,
their transforms, and their exact artifact hashes are rechecked together.

This is a TinyTapeout research prototype, not a production-qualified radio.
Periodically switched mixer noise figure requires a periodic-noise simulator
or first-silicon measurement; foundry mismatch yield, package/board effects,
and measured beam patterns remain explicit residuals. The official TinyTapeout
workflow is the final fabrication handoff gate. See
[the pre-silicon plan](docs/presilicon_plan.md) for the exact distinction.

## Reproduce the submission checks

```sh
make submission-artifacts
make test
make release-check
```

The GDS workflow regenerates the wrapper artifacts, rejects any diff, runs the
V2 submission-contract tests, compiles the boundary Verilog, then invokes the
pinned Tiny Tapeout custom-GDS and precheck actions.

## Repository history

The original two-channel experiment is retained only as explicitly named
legacy material, principally `spec/beamformer_v1.md`, the original behavioral
and SPICE models, and their tests. Those files are useful provenance but are
not read by the active V2 submission workflow.
