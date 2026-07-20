# Beamformer v1 electrical specification

Status: iteration-one implementation freeze. This specification describes the
minimal always-on binary-weight core represented by the release GDS.

## Purpose

Demonstrate coherent two-channel narrowband receive beamforming on Tiny
Tapeout while keeping antenna matching, LNA gain and the first RF conversion
off-chip.

The chip accepts two phase-coherent second-IF signals. Each channel is mixed
with a common LO. Selecting the LO polarity for channel 2 implements a 0- or
180-degree weight. The downconverted channel currents are summed and presented
as a differential voltage for a high-impedance external receiver.

## Tiny Tapeout target

- Process: SKY130A.
- Initial area target: one 1x2 analog slot.
- Supply: VDPWR = 1.8 V; no 3.3 V dependency in v1.
- Analog pins:
  - `ua[0]`: low-IF input 1.
  - `ua[1]`: low-IF input 2.
  - `ua[2]`: beamformed differential output P.
  - `ua[3]`: beamformed differential output N.
- Dedicated `clk`: in-phase LO input.
- `ui_in[0]`: channel-two 180-degree weight select (low=sum, high=difference).
- `ena` and `rst_n`: reserved boundary inputs with no analog effect in this
  minimal iteration.
- Channel-only modes, shutdown, gain control, and finer phase weights are
  deferred to a later iteration.
- Unused digital outputs must be tied low. Optional LO/debug outputs must be
  disabled by default to minimize coupling.

## Nominal signal plan

- Input center frequency: 5 MHz.
- LO frequency: 4 MHz.
- Beamformed output center frequency: 1 MHz.
- Initial useful modulation bandwidth: 100 kHz.
- Input amplitude: 10 to 30 mV peak-to-peak per channel.
- Nominal internal input common mode: approximately two-thirds of `VDPWR`
  (approximately 1.20 V at 1.80 V).
- External inputs are AC coupled and phase coherent.
- Output is measured differentially with a high-impedance load; a 50-ohm load
  is not a v1 operating condition.
- The 2 MHz two-pole filter used by the simulation measurement fixture is
  external. A large on-chip IF capacitor is not part of v1.

The stretch experiment is a 31 MHz input, 30 MHz LO and 1 MHz output. The
intermediate 10 and 20 MHz LO points likewise keep the input 1 MHz above the
LO. These higher-clock modes are characterized against the 20 dB release
floor but are not v1 operating ratings.

## Architecture

Each channel consists of a single-ended-to-differential NMOS transconductor
and an NMOS commutating mixer. Both mixer output currents connect directly to
a shared differential resistive load. Channel 2 selects either LO polarity.
A shared bias generator and symmetric physical construction minimize channel
mismatch. The external `clk` is buffered into complementary LO phases on-chip.

No on-chip 50-ohm match, inductor, transformer or transmission-line phase
shifter is permitted in v1.

## Tiny Tapeout interconnect envelope

Every external analog signal simulation must support independent values for:

- series path resistance: 0 to 500 ohms;
- shunt path capacitance: 0 to 5 pF;
- external load capacitance: 0 to 10 pF; and
- high-impedance load resistance: nominally 1 Mohm.

The two input paths must be varied independently. Equal parasitics alone do not
verify beamforming robustness.

## Provisional signoff requirements

- All modes operate across the selected process, voltage and temperature grid.
- Bias startup succeeds from power-off and from deliberately adverse initial
  conditions.
- Core channel-to-channel gain mismatch is at most 0.5 dB at the nominal
  frequency.
- Core channel-to-channel phase mismatch is at most 3 degrees at the nominal
  frequency.
- The full modeled path target is at most 1 dB gain mismatch and 8 degrees
  phase mismatch.
- Nominal constructive combining has no clipping for the specified input
  range.
- Nominal destructive combining produces at least a 20 dB null.
- Typical or externally calibrated null target is at least 25 dB.
- Output is stable for 0 to 10 pF external load.
- Across the deterministic supply sweep, output common mode remains above
  1.0 V and at least 0.10 V below the active VDPWR value; a fixed absolute
  ceiling is not used for the intentional 1.62-to-1.98 V characterization.
- Total active supply current target is below 5 mA.
- The binary phase-select transition must not create destructive current.

## Physical constraint contract

These requirements are release gates, not placement suggestions:

- matching-critical channel MOS devices use equal split halves in A/B; B/A
  common-centroid placement with equal device geometry, orientation, contact
  style, and local breakout direction;
- equal input-bias and differential-load resistors use mirrored pair placement
  about their corresponding axes; the unequal VCM divider preserves its
  intentional 1:2 top/bottom resistance ratio and symmetric local breakout;
- local device escape is 0.32 um M2 and named signal tracks/risers are 0.40 um
  M3/M4; widening a signal requires a new extracted-capacitance comparison;
- aggregate M3/M4 route-length mismatch is at most 2% for `ua[0]`/`ua[1]`
  and at most 1% for `ua[2]`/`ua[3]`, with equal via-1/2/3 site counts;
- each upper/lower input-to-GM endpoint, differential output-load endpoint,
  and switch-drain-to-output endpoint pair is at most 2% total M3/M4 length
  mismatch with equal via-site counts;
- matched internal GM and tail nets are at most 2% total M3/M4 length
  mismatch; explicitly listed via-3 deltas may be at most two sites for GM and
  one site for the tail tree where legal local branches are asymmetric;
- same-layer overlap between different named nets and a via cut overlapping
  another net's adjacent metal are always fatal;
- every named generated route is one connected nonzero-area metal/via
  component; a same-net floating stub, landing, or via island is always fatal;
- ordinary M4 routes maintain at least 0.30 um physical clearance from every
  top-edge TinyTapeout M4 pin rectangle; only the named `clk` and select routes
  may intentionally enter their own pins;
- unrelated M3/M4 routes may not enter the full two-dimensional MIM-capacitor
  footprint; the capm/via-3 overlap emitted inside the PDK PCell is intentional;
- every route run starts from clean placement, and every extraction consumes a
  route generated from the current manifest, because Magic paint is additive;
- 4/10/20/30 MHz extracted clock checks require less than 50 ps paired-channel
  skew, less than 150 ps complementary skew, and less than 250 ps edge time;
  aggregate LO Manhattan length remains diagnostic rather than a substitute for
  the electrical timing gate; and
- post-layout electrical signoff consumes a zero-pruning distributed-RC view
  produced by `extract do resistance` and `ext2spice extresist on`. A separate
  gate must prove fresh `.res.ext` annotations, positive explicit resistor
  segments, internal RC nodes, preserved devices, distributed capacitance, and
  resistor-graph participation by every manifest electrical net.

The flattened emitted GDS must additionally have zero project-audit markers for
M3/M4 spacing, M4 minimum width and connected area, and capm-to-unrelated-M3
interaction before it enters the official TinyTapeout precheck.

## Verification gates

1. The Python golden model passes all unit tests and emits a phase sweep.
2. The ideal-SPICE architecture matches the golden null calculations.
3. Each transistor-level block passes DC, AC and transient characterization.
4. Full schematic passes PVT, mismatch and interconnect regressions.
5. Layout is DRC clean and extractor-topology equivalent; independent
   foundry-qualified LVS remains an explicit open risk until completed.
6. Extracted blocks and representative full-tile cases pass the same metrics.
7. A hardware emulator runs the same phase sweep and automated measurement
   sequence intended for silicon.
8. The Tiny Tapeout submission checks pass from a pinned tool and PDK version.
