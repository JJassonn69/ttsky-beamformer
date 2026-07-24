# V2 pre-silicon validation plan

This plan applies to the exact physical candidate with SHA-256
`1b76aba2cf2362071e248fdeb6532e22ab6a928f1b8ce9f5c35393381aa89741`.
Results from an older GDS or extracted netlist cannot satisfy a current gate.

## Current candidate gates already passing

- exact 2x2 Tiny Tapeout boundary and six-analog-pin contract;
- Magic full-chip DRC, GDS import, and extraction feedback: zero;
- direct-GDS cut, enclosure, floating-stub, route-island, MIM-clearance, and
  signal-to-power-short checks;
- final extracted named-terminal checks for 156 signal-path instances, all 15
  service/direct routes, all 16 trim routes, all 12 phase-control routes, all
  four quadrature roots, the four 47-unit tail banks, and the VCM varactors;
- route, placement, power, KLayout marker-delta, and flat-GDS audits; and
- frozen source and candidate hashes in
  `build/v2/signoff/gate3_manifest.json`.

The current-hash 120 us startup run and 64-case trim calibration pass. Older
candidate matrices remain regression evidence only and cannot satisfy a gate
for this hash.

## Hierarchical signoff policy

Validation proceeds through the gates below in order.  A failing gate reopens
that gate and invalidates later-gate release claims for a replacement GDS.  Do
not launch an exhaustive distributed-RC codebook, full trim matrix, or broad
PVT matrix for a candidate that has not passed the cheaper preceding gates.
Completed results from an older hash remain regression evidence only.

### Gate 0: requirements and test contract

- Freeze supply, frequency, input amplitude, output load, beam modes, trim
  behavior, startup time, power, common-mode, gain, rejection, noise, and
  linearity limits.
- Define both hard functional limits and engineering margin targets.  A value
  that barely crosses a hard threshold is not automatically a robust design.
- Bind every report to the schematic, GDS, extracted netlist, models, corner,
  simulator, and test-harness hashes.

### Gate 1: architecture and bias screening

- Use fast schematic/base-extracted, operating-point-started, zero-input or
  short-window simulations to sweep candidate tail counts and the small set of
  limiting PVT corners.  Correlate only the limiting candidate/corner once
  against distributed RC before freezing the architecture.
- Start measurement no earlier than 2 us when a non-default proxy trim is
  serially programmed near 0.842 us.  A shorter run may reduce turnaround, but
  an unsettled window is not valid architecture evidence.
- Check output common mode, current, power, bias stability, and active-device
  operating-region margin.  Common mode is a screening symptom; transistor
  `VGS-VTH` and `VDS-VDSAT` margin is the deciding evidence.
- Reject candidates without running complete beam or trim matrices.
- Use `make v2-tail-screen` for the proxy sweep.  On the predecessor
  36-fixed-unit layout, trim codes 4, 5, and 6 proxy proposed 32-, 33-, and 34-fixed-unit
  banks at reset code 8 by preserving the total active-unit count.

### Gate 2: selected schematic candidate

- Freeze one tail-bank count and one reset code.
- Re-run nominal four-beam function, representative constructive/destructive
  cases, trim monotonicity/endpoints, and limiting-corner headroom.
- Check gain, current, and device-region margins before any layout regeneration.

### Gate 3: physical implementation

- Regenerate placement and routing from authoritative generators; never patch
  only the review GDS.
- Pass Magic DRC, extraction topology, direct-GDS KLayout/flat rules, matching,
  route-length/via constraints, floating-island checks, and independent LVS
  when the accessible SKY130 flow permits it.
- Freeze the candidate GDS and extracted-netlist hashes before electrical
  signoff begins.

### Gate 4: targeted post-layout electrical closure

- Run base-extracted and distributed-RC nominal four-beam checks.
- Run startup, the limiting PVT/headroom cases, trim endpoints/default, and
  representative constructive/null cases.
- Compare schematic, base extraction, and distributed RC so an extraction or
  routing regression is visible before launching exhaustive matrices.

### Gate 5: robustness and characterization

- Run the largest defensible device-mismatch campaign supported by the
  available models. The present open flow uses published geometry-scaled
  SKY130 coefficients for a 60-seed sensitivity campaign. It must report its
  exact binomial bound and limitations and must not be called foundry yield.
- Characterize frequency, input amplitude, 1 dB compression, IIP3, noise,
  output resistance/capacitance, supply sensitivity, and clock duty-cycle and
  jitter sensitivity.
- Produce plots with numeric source data, conditions, units, and artifact
  hashes.

### Gate 6: release-only exhaustive closure

- Run the complete 20-case beam codebook and required PVT/trim matrices only on
  the frozen release candidate.
- Regenerate the datasheet and evidence hashes, push the exact candidate, and
  require a green official Tiny Tapeout custom-GDS precheck.
- Fabrication readiness requires every electrical and physical gate to refer
  to the same frozen hashes.

## Current gate

The selected 32-fixed-unit tail bank with reset trim code 8 has passed the
architecture screen, the frozen physical/topology Gate 3, and the bounded
post-layout electrical Gate 4.  The exact final
GDS hash is
`1b76aba2cf2362071e248fdeb6532e22ab6a928f1b8ce9f5c35393381aa89741`.
The local project has completed Gates 5 and the simulation portion of Gate 6
on this frozen candidate. The official Tiny Tapeout custom-GDS/precheck run is
the remaining fabrication handoff.

The ten hash-bound Gate 4 cases pass: nominal base and distributed-RC
constructive response, zero-input background in both views, a representative
distributed-RC null, SF/FF headroom, trim codes 0 and 15, and a 120 us cold
start.  Background-corrected representative rejection is 74.08 dB and the
base-to-distributed-RC constructive delta is 0.11 dB.  These results are
consolidated in `build/v2/signoff/gate4_targeted_manifest.json` and independently
checked by `make v2-gate4` without rerunning SPICE.

The bounded Gate 5 pilots and release expansions pass: amplitude/compression,
RF frequency, output load, clock duty/jitter, two-tone linearity, 60 modeled
MOS-mismatch seeds, the exact 20-case distributed-RC codebook, and focused
final PVT endpoints. All 60 mismatch samples meet both the hard functional
gate and 12 dB engineering target; the exact one-sided 95% zero-failure lower
bound is 95.13%. The raw beam matrix has 61.05 dB minimum rejection and
0.244 dB constructive spread. If a circuit or layout change alters the frozen
hash, stop immediately and return the replacement through the earliest
affected gate.

## Characterization-figure policy

Simulation runs must retain numeric sweep data, conditions, artifact hashes,
and units so they can produce engineering curves instead of only green/red
status. The release datasheet includes the beam response matrix, gain-trim
transfer, mismatch distribution, electrical sensitivity, two-tone linearity,
and cold-start milestones. Future silicon work should add:

- conversion gain and rejection versus RF/LO frequency;
- continuous incident-phase beam patterns, null depth, and sidelobes;
- continuous output amplitude versus input amplitude and measured P1dB/IIP3;
- output noise or noise figure versus frequency;
- gain/common-mode/settling versus output resistance and capacitance;
- measured clock duty-cycle and jitter sensitivity; and
- measured before/after-trim distributions and cancellation-yield CDFs.

Run `make datasheet-figures` to regenerate the current hash-bound SVG set and
`v2/evidence/datasheet_figures.json`. A figure is evidence only when its source
report hashes match the current candidate and extracted netlist.

## Release policy

A green Tiny Tapeout precheck proves that the files fit the shuttle interface;
it does not prove analog performance or yield. Fabrication readiness requires
both the official file check and every electrical gate above to be bound to the
same GDS and extracted-netlist hashes.

The machine-readable status is maintained in
`v2/evidence/latest_validation.json`; detailed requirements and limits are in
`v2/docs/datasheet.md` and `v2/spec/beamformer_v2.md`.
