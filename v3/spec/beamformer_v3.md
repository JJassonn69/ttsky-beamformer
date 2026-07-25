# Beamformer V3A architecture contract

Status: architecture Gate 1 and bounded one-channel Gate-2B PVT/linearity
checkpoint implemented. This is not a physical layout or fabrication claim.

## Objective

Replace V2's independent four-state phase selector and on/off tail-current
trim with a constant-`gm` Cartesian vector cell.  V3 must add meaningful
beamforming freedom while preserving the validated low-IF signal plan and the
six-pin analog interface.

V3A remains receive-only.  A detector/ADC, 50-ohm output driver, direct
10.5 GHz interface, and reciprocal TX path are separate research gates and
must not be added before the vector core closes.

## Frozen inheritance from V2

- four single-ended, AC-coupled, phase-coherent element inputs;
- one high-impedance differential summed output;
- nominal 5 MHz element input, 4 MHz quadrature LO, and 1 MHz output;
- nominal 16 MHz master clock and 1.8 V supply;
- the approximately 1.2 V AC-coupled input common-mode reference and its
  startup-valid threshold discipline;
- four matched channel slices above the existing analog-pin pitch;
- balanced quadrature distribution, centered differential summing, and safe
  blanked configuration updates; and
- no project signal on Metal 5 and no implied on-chip 50-ohm termination.

## Constant-gm vector cell

One channel contains 15 equal unit slices assigned to four binary groups:

| Group | Unit slices | Control |
| --- | ---: | --- |
| 0 | 1 | two-bit Cartesian-axis code |
| 1 | 2 | two-bit Cartesian-axis code |
| 2 | 4 | two-bit Cartesian-axis code |
| 3 | 8 | two-bit Cartesian-axis code |

Each group is always active and must select exactly one axis:

| Code | Axis | Complex basis |
| ---: | --- | --- |
| `00` | I+ | `+1` |
| `01` | Q+ | `+j` |
| `10` | I- | `-1` |
| `11` | Q- | `-j` |

The channel coefficient is the vector sum of the four weighted axes.  The
8-bit raw word stores the two-bit axis code for groups 1, 2, 4, and 8 from
least to most significant bits.  There is deliberately no disabled axis code.
Channel disable remains a separate blanked control.

This creates 256 raw words and a 16-by-16 rotated Cartesian constellation.
Points near one radius implement phase rotation; inner points implement
amplitude taper or calibration.  Four groups are the V3A baseline.  A fifth
16-unit group is a stretch option only if schematic and physical gates show
that the extra local routing, clock load, noise, and area are justified.

## Modes

### Legacy cardinal mode

All four binary groups select the same axis.  This exactly represents the
V2 phase alphabet of 0, 90, 180, and 270 degrees at full vector magnitude and
provides the direct V2/V3 comparison mode.

### Eight-state beam mode

A deterministic lookup table selects eight approximately constant-radius
vectors at 45-degree target spacing.  Four even-index progressive-phase beams
retain the four orthogonal DFT directions.  Four intermediate beams add
steering directions but are not additional orthogonal spatial dimensions.

### Raw-vector mode

Each channel receives one 8-bit raw vector word.  Four channels therefore use
a 32-bit serial coefficient packet.  Raw mode supports external phase/gain
calibration, amplitude tapering, and experimental null steering.  Requested
words are committed atomically while all channels are blanked for one LO
period, following the proven V2 update discipline.

## Initial control contract

- `ui_in[2:0]`: automatic eight-beam index;
- `ui_in[3]`: automatic table / raw-vector mode;
- `ui_in[7:4]`: channel enable mask;
- `uio_in[0]`: configuration clock;
- `uio_in[1]`: configuration data;
- `uio_in[2]`: atomic configuration latch; and
- one 32-bit LSB-first packet containing CH0 through CH3 raw vector words.

The pin mapping is provisional until the RTL gate.  Unused digital outputs
must remain static during analog measurements.

## Architecture Gate 1

The executable model must prove:

1. every raw word accounts for all 15 unit slices exactly once;
2. the 256 words produce 256 deterministic nonzero constellation points;
3. the legacy cardinal codes exactly reproduce the V2 phase alphabet;
4. an eight-state phase table has no more than 4 degrees ideal phase error and
   no more than 0.35 dB ideal magnitude span;
5. the four even-index DFT beams remain mutually orthogonal in the ideal model;
6. continuous-angle array response and arbitrary raw coefficients are
   executable and deterministic; and
7. the configuration packet round-trips exactly.

These are ideal quantization gates, not transistor performance guarantees.

## Architecture Gate 2: one-channel schematic

No V3 floorplan may begin until one complete channel demonstrates:

- all selected vector states and quadrant transitions;
- phase error, magnitude ripple, and calibration range over PVT;
- constant total bias current and bounded input/output impedance movement;
- output common mode above 0.8 V at every required PVT/vector state;
- less than 1 dB compression at 50 mV-peak input;
- LO feedthrough, image/spur response, noise, and code-transition behavior;
- load response through the Tiny Tapeout analog path model; and
- mismatch using separate calibration and validation samples.

The Gate-2B starting geometry uses 0.42 um unit gm devices, 0.65 um
commutating devices, and fifteen equal 2.5333 um by 0.50 um tail sinks. The
tail widths sum to the V2 38 um mirror output. The 0.65 um switch choice is
provisional until LO-driver loading is included: it must preserve at least
95% tail-current compliance at the observed minimum tail voltage and keep
the gm drain above its source through every LO transition. Brief commutation
at the LO crossing is not mislabeled as a static saturation proof.

The simple eight-phase hard-selector channel is the explicit fallback.  A raw
R-2R ladder is not a valid main-path weighting solution unless a local buffer
proves that it cannot pull VCM or shared bias.

## Architecture Gate 3: physical feasibility

Before four-channel schematic promotion, use measured PCell dimensions to
compare 15- and 31-slice layouts.  The chosen channel must fit as one matched
slice directly above its input pin.  Unit slices must be interdigitated with
common-centroid assignment, edge dummies, equal contact populations, local
grounding, and equal switch-route topology.  Additional vector hardware must
not be placed in a distant empty region and connected by unmatched analog
routes.

## Initial engineering targets

| Metric | V3A target |
| --- | ---: |
| Guaranteed phase states | 8 |
| Ideal LUT phase error | <= 4 degrees |
| Ideal LUT magnitude span | <= 0.35 dB |
| Calibrated transistor-level phase error | <= 5 degrees |
| Calibrated phase-state gain ripple | <= 0.5 dB |
| Useful amplitude-control range | >= 12 dB |
| Output common mode over required PVT | >= 0.8 V |
| Compression at 50 mV peak | < 1 dB |
| Total nominal core power | <= 3 mW |
| Exact-layout base-to-RC loss | < 1 dB |

Targets may be tightened after the one-channel circuit is selected.  They may
not be relaxed merely to accept a completed layout.

## 10.5 GHz system boundary

V3 remains a low-IF complex-weight beamformer.  A future 10.5 GHz array uses
four coherent external LNA/mixer paths driven from one RF LO.  Those paths
produce four phase-preserving 5 MHz element signals for V3.  Raw vector words
can correct fixed phase and gain offsets in the external paths.  Wideband
beam-squint correction would require true time delay or digital beamforming
and is outside V3A.
