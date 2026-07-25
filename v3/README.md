# Beamformer V3 workspace

V3 is an architecture-development branch derived from the frozen V2 release
commit `b7eae2e6ecf20b1141d15029503c345dacc71b99`.  Nothing under `v2/`, and none
of the active Tiny Tapeout submission artifacts, is modified by the initial V3
work.

The proposed V3A datapath is a four-channel, receive-only, constant-`gm`
Cartesian vector beamformer.  Each channel uses four binary groups of matched
unit slices with weights 1, 2, 4, and 8.  Every group remains active and is
steered to one of `I+`, `Q+`, `I-`, or `Q-`.  Their current-domain sum creates a
programmable complex channel coefficient without changing the total active
unit count.

Initial implementation scope:

- preserve the V2 5 MHz input, 4 MHz quadrature LO, 1 MHz differential output,
  six-analog-pin interface, 1.8 V supply, and 2x2 area target;
- guarantee the four legacy cardinal phases;
- target eight uniform phase states and expose all 256 raw vector words per
  channel;
- support phase and amplitude calibration from the same coefficient word; and
- prove the architecture in a golden model and one-channel SPICE before any
  V3 placement or routing is accepted.

Key files:

- `spec/beamformer_v3.md`: architecture and gate contract;
- `model/beamformer_v3.py`: executable constant-`gm` vector and array model;
- `spice/vector_channel_15.inc`: ideal-current and matched-MOS one-channel cells;
- `rtl/vector_control_core.v`: eight-beam LUT and 32-bit raw coefficient control;
- `evidence/implementation_checkpoint.json`: hash-bound early implementation results; and
- `tests/`: architecture, SPICE topology, RTL, and evidence guards.

Run the first architecture gate with:

```sh
python3 -m unittest discover -s v3/tests -p 'test_*.py' -v
python3 v3/model/beamformer_v3.py summary
```

Run the first real-device, one-channel vector-weighting gate:

```sh
python3 v3/tools/run_one_channel_vector_sweep.py --states 8
python3 v3/tools/run_one_channel_vector_sweep.py --states 8 --bias mos
```

This Gate-2A circuit intentionally uses fifteen equal ideal tail-current
sources while retaining real SKY130 transconductors and mixer switches. It
tests the new vector topology before the MOS bias bank is sized. Gate 2B will
replace the ideal sources and add PVT, headroom, linearity, and mismatch.

The runner also accepts `--input-peak` and `--output-capacitance-pf`. The
first bounded TT sweep shows 0.155 dB worst compression at 50 mV peak. The
unbuffered output loses about 2.65 dB at 30 pF and 6.70 dB at 60 pF per pad,
so a roughly 10 pF-class differential receiver remains the intended load.

Run the bounded nominal two-tone pilot with:

```sh
python3 v3/tools/run_twotone_pilot.py
```

The next electrical gate is selector/tail transition settling, absolute PVT
gain calibration, spur/noise scope, and mismatch. Physical placement remains
blocked until those circuit questions close.

V3 is not yet a layout, submission, or fabrication candidate.
