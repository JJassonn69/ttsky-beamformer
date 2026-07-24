# V2 latest validation status

Date: 2026-07-25<br>
Candidate GDS SHA-256: `1b76aba2cf2362071e248fdeb6532e22ab6a928f1b8ce9f5c35393381aa89741`
Submission GDS SHA-256: `320e9b448ac66377691698ab5d351cebd90da2f2a532019675e213205625933e`

Release status: `fab_ready_research_prototype`. Local physical and bounded
electrical signoff pass, and the official TinyTapeout workflow passed for
commit [`053cfe1`](https://github.com/JJassonn69/ttsky-beamformer/commit/053cfe118ad701c447fe62d0a5d6b7804ab58661):
[`gds` run 30129235841`](https://github.com/JJassonn69/ttsky-beamformer/actions/runs/30129235841).

## Headline evidence

- Magic full-chip DRC: 0 errors; direct flat-rule counters: all zero.
- Exact submission-GDS geometry regression: 20/20 base codebook cases pass;
  55.23 dB minimum raw rejection and 0.227 dB constructive spread.
- Exact submission-GDS distributed-RC nominal: 80,129 positive metal
  resistors, 23.357 mV RMS output, 0.109 dB base-to-RC loss, and less than
  0.1 fs phase-tree skew. The RC-only run uses the physical varactors
  linearized at the 1.2 V common-mode operating point for numerical
  convergence; the exact-base codebook uses the nonlinear varactor model.
- Distributed RC: 95,139 resistors,
  34,054 capacitors, and
  254/
  254 named routes covered.
- Complete nominal RC codebook: 61.05 dB
  minimum raw rejection and 0.244 dB
  constructive spread.
- MOS mismatch sensitivity: 60/60 pass;
  minimum corrected rejection 36.49 dB;
  one-sided 95% modeled pass-probability lower bound
  95.13%.
- Trim span: 2.337–
  2.343 dB; deterministic injected mismatch
  calibrates to 0.059 dB spread.
- 50 mV-peak compression: 0.370 dB;
  10 mV/tone fundamental-to-worst-IM3 separation:
  49.20 dB.
- Conservative first-silicon enable delay: 120 us.

## Honest residuals

- Mixer noise figure needs a periodic-noise simulator or first-silicon measurement.
- The 60-seed open-PDK mismatch campaign is sensitivity evidence, not foundry yield.
- Package, PCB, antenna, 50-ohm drive, and measured beam patterns remain first-silicon work.
- Independent foundry-qualified LVS is unavailable in the present open flow.

The machine-readable record is [`latest_validation.json`](latest_validation.json),
and all plotted datasets and source hashes are in
[`datasheet_figures.json`](datasheet_figures.json).
