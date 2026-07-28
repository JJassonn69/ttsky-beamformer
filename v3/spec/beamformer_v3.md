# Beamformer V3A architecture contract

Status: the architecture, bounded electrical campaign, four-channel physical
integration, distributed-RC extraction, exact Tiny Tapeout packaging, and
internal signoff are complete. The frozen candidate is SHA-256
`824e38f94ce4fbff84d0c079dcb059d6944bca7569a0f657134c318f31553c14`.
Official GitHub custom-GDS/precheck attestation and silicon measurement remain
open. This contract retains the earlier gate-by-gate decisions below as design
provenance; the current release summary is `v3/evidence/submission_gate.json`.

## Objective

Replace V2's independent four-state phase selector and on/off tail-current
trim with a constant-`gm` Cartesian vector cell.  V3 must add meaningful
beamforming freedom while preserving the validated low-IF signal plan and the
six-pin analog interface.

V3A remains receive-only.  A detector/ADC, 50-ohm output driver, direct
10.5 GHz interface, and reciprocal TX path are separate research gates and
are not implemented in this frozen candidate.

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

The rejected Gate-2B starting geometry used 0.42 um by 0.30 um unit gm
devices and fifteen equal 2.5333 um by 0.50 um tail sinks. An open-PDK
coefficient mismatch screen showed that this minimum-area choice missed both
the 5-degree phase and 0.5 dB ripple targets. The promoted pre-layout geometry
uses 0.84 um by 0.60 um gm devices, 5.0667 um by 1.00 um tail sinks, and a
64 um by 1.00 um shared diode reference. Doubling both dimensions preserves
W/L and mirror ratio while providing four times the mismatch area. The 0.65
um switch is unchanged. It must preserve at least
95% tail-current compliance at the observed minimum tail voltage and keep
the gm drain above its source through every LO transition. Brief commutation
at the LO crossing is not mislabeled as a static saturation proof.

The simple eight-phase hard-selector channel is the explicit fallback.  A raw
R-2R ladder is not a valid main-path weighting solution unless a local buffer
proves that it cannot pull VCM or shared bias.

The blanked control update must hold every group LO gate and channel tail gate
low for one complete 4 MHz LO period. At TT with behavioral group-selector
voltages, bounded 5 ns edges, and a real NMOS bias pass/pulldown pair, the
transistor-level analog path must return within 5% amplitude, 5 degrees phase,
and 10 mV common mode of its final value within 2 us for all 56 ordered
transitions between the eight required states. Final selector-cell and route
RC must be rechecked after extraction.

The square-wave mixer intentionally produces a 9 MHz sum product and odd-LO
harmonic products. The raw 9 MHz term is not treated as LO feedthrough. The
defined high-impedance receiver interface therefore includes the same two-pole
2 MHz low-pass response used by the bench model; its worst deterministic signal
spur must remain below -20 dBc. Raw and filtered spectra must both remain in
the evidence.

Small-signal `.noise` with the LO held in each of four DC states is only a
bounded diagnostic. It does not include cyclostationary noise, mixer folding,
LO phase noise, or clock-edge noise. The driven periodic-noise equivalent uses
VACASK on the complete 15-slice channel with 4 MHz quadrature switching, four
deterministic seeds per required state, a 100 us post-settle record, intrinsic
noise from 10 kHz to 64 MHz, and the specified two-pole 2 MHz receiver. Its
mean 10 kHz--2 MHz output noise is 41.62 uV RMS, and state means span 2.154 dB.
The noisiest state mean is 47.91 uV RMS. A three-amplitude linearity run gates
the required reduced-noise extrapolation at R-squared 0.99999496 and 0.080 dB
spread.

An independent ngspice held-state/Fourier-folding calculation covers all 32
word/state snapshots and predicts 34.98 uV RMS over the directly comparable
band. The +1.51 dB difference passes the declared +/-3 dB agreement limit.
Its 10 Hz--2 MHz result is 35.10 uV RMS; combining only its unresolved
10 Hz--10 kHz increment with the noisiest driven state gives a conservative
48.01 uV RMS result and 38.6 dB minimum nominal SNR at 5 mV-peak input. This
cross-checked equivalent closes the schematic periodic-noise gate, while
remaining explicitly weaker than native PNoise. Clock-source phase noise,
package/board noise, extracted-layout parasitics, and silicon correlation are
not covered and remain later gates.

Mismatch calibration is per die, not one universal factory lookup table. Each
mismatch realization must select its own frozen eight-word codebook from a
known 20 mV-peak calibration tone, then pass a separate 5 mV-peak validation
transient without using validation results for selection. The calibration and
validation decks share the same device mismatch realization because they
represent two measurements of the same fabricated die. This deterministic
screen does not model calibration measurement noise, temperature drift,
passive mismatch, spatial correlation, package effects, or foundry yield. A
disjoint-population global-codebook run is retained only as a deliberately
harsh diagnostic; its failure does not substitute for per-die calibration.
The actual Gaussian device-factor values, rather than only RNG seeds, are
frozen and hashed so Apple ARM and Ubuntu x86 reproduce byte-identical decks.
The bounded 16-die campaign passes after independent 5 mV validation with
4.356 degrees worst phase error, 0.408 dB worst gain ripple, and 1.574 V
minimum output common mode. This is a design-sensitivity result, not a yield
claim.

## Architecture Gate 3: physical feasibility

Before four-channel physical promotion, use measured PCell dimensions to
compare 15- and 31-slice layouts.  The chosen channel must fit as one matched
slice directly above its input pin.  Unit slices must be interdigitated with
common-centroid assignment, edge dummies, equal contact populations, local
grounding, and equal switch-route topology.  Additional vector hardware must
not be placed in a distant empty region and connected by unmatched analog
routes.

The selected dimension-only candidate is a 3-column by 5-row active matrix:

| Row | Left | Centre | Right |
| --- | ---: | ---: | ---: |
| 0 | 8 | 8 | 8 |
| 1 | 4 | 8 | 4 |
| 2 | 2 | 1 | 2 |
| 3 | 4 | 8 | 4 |
| 4 | 8 | 8 | 8 |

Every binary group has centroid `(1, 2)` in unit-pitch coordinates. Use
device-row edge dummies horizontally, conservative dummy coverage above and
below, inversion-paired R0/MY units, and one shared guard. Pinned Magic 8.3.676
measurements estimate this candidate at 15.74 um wide by 93.99 um high, leaving
3.58 um on the 19.32 um input pitch. A complete dummy *unit* at each horizontal
edge leaves only 1.02 um and is explicitly rejected. With the electrical gates
closed, these bounds may now guide matched floorplanning; they are not a GDS
or physical-signoff claim.

The local selector route pilot fixes one additional production constraint:
functional standard cells must be separated horizontally by one 0.46 um filler
site, while alternating rows remain vertically contiguous. The filler sites
remove LI pin-access conflicts and preserve row power-rail continuity.
Vertical row channels are forbidden unless a later official-deck experiment
proves legal well geometry; the tested 0.68 um channel created 33 n-well
spacing markers. The selected one-channel pilot is clean in OpenROAD, Magic,
flat extraction, and the directly applicable Tiny Tapeout KLayout geometry
decks, but does not authorize the four-channel or submission GDS.

The isolated shared-reference pilot is also closed. Its 8-by-8 um folding
extracts as eight diode-connected 8/1 um fingers, and the exact GDS passes
Magic DRC plus the directly applicable Tiny Tapeout geometry decks. The
balanced M2 tree has four 37.98 um drawn branches and endpoint-rooted Magic
`extresist` gives 9.1564 ohm for every post-star branch, or 0.0 percent
mismatch against the 1.0 percent limit. The 22.3824 ohm common route is
upstream of the named star and therefore affects absolute bias settling, not
channel-to-channel matching. These results authorize integration of the
unchanged reference/tree pilot; they do not authorize the top-level GDS.

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
