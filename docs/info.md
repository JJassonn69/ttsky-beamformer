## How it works

This project is a two-channel narrowband receive beamformer for phase-coherent
5 MHz intermediate-frequency signals. Each analog input drives a matched NMOS
transconductor and commutating mixer. The 4 MHz `clk` input is converted into
complementary local-oscillator phases on chip. The mixer currents share a
differential load, producing the 1 MHz difference-frequency signal on
`BEAM_OUT_P` and `BEAM_OUT_N`.

Set `CH2_PHASE_180` low to combine equal-phase inputs constructively. Set it
high to exchange the channel-two LO phases and apply a 180-degree weight. The
latter mode demonstrates spatial cancellation when the two inputs have equal
amplitude and phase.

The chip intentionally contains no 50-ohm RF match, inductor, transformer or
large IF filter. These functions are more predictable and testable off-chip.

The release operating point remains a 4 MHz clock with 5 MHz inputs. The final
parasitic layout has additionally been characterized at 10, 20, and 30 MHz;
for those modes keep the input 1 MHz above the clock. Higher-clock operation is
for characterization until package and board parasitics are included.

See the [complete engineering datasheet and iteration handoff](datasheet.md)
for the circuit inventory, operating envelope, simulation results,
physical-signoff provenance, known risks, and next-revision plan.

## How to test

1. Apply 1.8 V to `VDPWR` and ground to `VGND`. The minimal analog core is
   always active while powered; `ena` and `rst_n` are reserved in this revision.
2. Drive `clk` with a 0-to-1.8 V, 4 MHz square wave.
3. AC-couple two phase-coherent 5 MHz sine waves of 10 mVpp into
   `IF_INPUT_1` and `IF_INPUT_2`.
4. Measure `BEAM_OUT_P - BEAM_OUT_N` with a high-impedance differential probe
   or instrumentation amplifier followed by an external 2 MHz low-pass
   filter.
5. With `CH2_PHASE_180=0`, verify a strong 1 MHz output. With
   `CH2_PHASE_180=1`, verify cancellation. Sweep the phase of input two through
   360 degrees and record the constructive peak and null depth.

Do not terminate an analog output directly in 50 ohms. Keep every pin between
`VGND` and `VDPWR`.

## External hardware

- two phase-coherent, independently phase-adjustable 5 MHz signal sources;
- one 0-to-1.8 V, 4 MHz clock source;
- AC-coupling capacitors for both analog inputs;
- a high-impedance differential receiver or oscilloscope probe; and
- an external low-pass filter with approximately 2 MHz cutoff.
