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
- Nominal internal input common mode: approximately 0.9 V.
- External inputs are AC coupled and phase coherent.
- Output is measured differentially with a high-impedance load; a 50-ohm load
  is not a v1 operating condition.
- The 2 MHz two-pole filter used by the simulation measurement fixture is
  external. A large on-chip IF capacitor is not part of v1.

The stretch experiment is a 30 MHz input, 29 MHz LO and 1 MHz output. It is
not a v1 signoff requirement.

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
- Total active supply current target is below 5 mA.
- The binary phase-select transition must not create destructive current.

## Verification gates

1. The Python golden model passes all unit tests and emits a phase sweep.
2. The ideal-SPICE architecture matches the golden null calculations.
3. Each transistor-level block passes DC, AC and transient characterization.
4. Full schematic passes PVT, mismatch and interconnect regressions.
5. Layout is DRC clean and LVS equivalent.
6. Extracted blocks and representative full-tile cases pass the same metrics.
7. A hardware emulator runs the same phase sweep and automated measurement
   sequence intended for silicon.
8. The Tiny Tapeout submission checks pass from a pinned tool and PDK version.
