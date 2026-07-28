## How it works

Think of the four inputs as four microphones hearing the same wave at slightly
different times. Each channel points its signal in a programmable direction on
a phase compass, and the chip adds all four. The selected arrival pattern lines
up and becomes strong; other patterns tend to cancel.

The `clk` pin accepts a nominal 16 MHz master clock. On-chip logic creates four
4 MHz quadrature phases. `BEAM_SELECT[2:0]` chooses one of eight automatic
coefficient sets. Raw-vector mode accepts one independent eight-bit phase/
amplitude word per channel through the three-wire serial interface. Four direct
enable bits can isolate channels.

The intended first operating point is four coherent 5 MHz inputs and a
differential 1 MHz output. The ports are high impedance. Use a low-capacitance
differential receiver and do not terminate the output directly in 50 ohms.

## How to test

1. Apply 1.8 V to `VDPWR` and ground to `VGND`; `VAPWR` is not used.
2. Hold `rst_n=0` and `ena=0` during power-up and wait at least 60 us after the
   supply is stable.
3. Apply a clean 16 MHz clock, release reset, select a beam, enable channels,
   and then assert `ena`.
4. Drive four phase-coherent 5 MHz signals into `ua[0]` through `ua[3]`,
   initially at 5 mV peak per input.
5. Measure `ua[4]-ua[5]` with a high-impedance, low-capacitance differential
   receiver and a low-pass response appropriate for the 1 MHz output.
6. Exercise all eight automatic beams, then calibrate raw words per channel.
7. Validate a frozen calibration using a separate stimulus level/data set.

The exact limits and configuration format are in the
[V3 datasheet](../v3/docs/datasheet.md).
