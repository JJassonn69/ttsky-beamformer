# V2 latest validation status

Date: 2026-07-24<br>
Candidate GDS SHA-256: `1b76aba2cf2362071e248fdeb6532e22ab6a928f1b8ce9f5c35393381aa89741`

Release status: `local_signoff_passed_official_tinytapeout_workflow_pending`. Local physical and bounded electrical signoff pass.
The official TinyTapeout workflow is pending for the exact artifacts below.

## Headline evidence

- Magic full-chip DRC: 0 errors; direct flat-rule counters: all zero.
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
