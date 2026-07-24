## How it works

Think of the four inputs as four microphones listening to the same repeating
wave from slightly different positions. The chip delays each channel by one of
four quarter-cycle choices, then adds all four channels. A wave arriving from
the selected direction lines up and adds strongly; waves with the wrong phase
pattern mostly cancel.

The `clk` pin accepts a nominal 16 MHz master clock. On-chip digital logic
creates four 4 MHz phases. `BEAM_SELECT_0/1` choose one of four fixed phase
patterns. `CH0_ENABLE` through `CH3_ENABLE` can isolate channels, and the
three-wire configuration interface loads manual phase and 4-bit per-channel
gain-trim settings.

The intended first operating point is four coherent 5 MHz inputs and a
differential 1 MHz output. The ports are high impedance; use AC coupling and a
high-impedance differential receiver. Do not terminate the output directly in
50 ohms.

## How to test

1. Apply 1.8 V to `VDPWR` and ground to `VGND`; do not apply a second analog
   supply because this design does not use `VAPWR`.
2. Hold reset active and all channels disabled during startup. Wait at least
   120 us after applying power for the simulated common-mode reference to
   settle, then apply a 0-to-1.8 V, 16 MHz clock and release reset.
3. AC-couple four phase-coherent 5 MHz signals into `ua[0]` through `ua[3]`.
4. Measure `ua[4] - ua[5]` with a high-impedance differential probe or
   instrumentation amplifier and a low-pass filter around the 1 MHz output.
5. Select each beam code and change the four input phases to match that code.
   The matching code should produce the strongest output; the three other
   codes should be substantially lower.
6. Test one channel at a time, then use the per-channel trim codes to reduce
   residual gain mismatch before repeating the four-channel test.

The exact pin table, configuration format, limits, and validation status are
in the [V2 datasheet](../v2/docs/datasheet.md).
