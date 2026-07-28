# Four-Channel Constant-gm Vector Beamformer V3

## 1. Release identity and status

This document describes the internally signed-off V3 custom-analog candidate
for the Tiny Tapeout SKY130 2x2 wrapper. It is a receive-only, four-element,
low-intermediate-frequency (low-IF) vector beamformer. It is not a direct
10.5 GHz RF front end.

| Item | Frozen value |
|---|---:|
| Top cell | `tt_um_jjassonn69_beamformer` |
| Process | SKY130A |
| Tile allocation | 2x2 |
| Die-area contract | 334.88 um x 225.76 um |
| Nominal supply | 1.8 V on `VDPWR`; `VGND` return |
| `VAPWR` | Not used |
| Analog pins used | 6 of 8 |
| Extracted device count | 6,037 |
| Analog / digital devices | 1,315 / 4,722 |
| Frozen GDS SHA-256 | `988ad4fb3509f4696c3865c3ac3b1058a7fe300133404641dc945da5017bb3a9` |
| Internal signoff | Passed |
| External release attestation | Passed: official Tiny Tapeout custom-GDS, viewer, precheck, and evidence jobs |

The frozen candidate is
`v3/frozen/submission/tt_um_jjassonn69_beamformer.gds`. The canonical submission
copy is `gds/tt_um_jjassonn69_beamformer.gds`. They must remain byte-identical.

## 2. What the circuit does

Each of the four input pins receives the same signal at a potentially different
arrival phase, as happens with four spatially separated antennas after RF
downconversion. The chip applies a programmable phase/amplitude coefficient to
each input and adds the four weighted currents. Signals arriving from the
selected direction line up and add; signals from other directions tend to
cancel.

The phase shifter is a constant-`gm` Cartesian vector cell. Every channel has
15 equal transconductor/mixer slices arranged as binary groups of 1, 2, 4, and
8. Every slice remains active; each group selects one of four quadrature axes:

| Two-bit group code | Selected axis |
|---:|---|
| `00` | I+ / 0 degrees |
| `01` | Q+ / 90 degrees |
| `10` | I- / 180 degrees |
| `11` | Q- / 270 degrees |

Keeping all 15 slices active makes the total channel transconductance and tail
loading much less dependent on beam code than an architecture that switches
slices off. Four weighted axis choices form an approximate vector of arbitrary
phase and controllable magnitude. The four channel currents meet at one
differential output collector.

## 3. Intended signal plan

| Signal | Nominal value | Notes |
|---|---:|---|
| Master digital clock | 16 MHz | Required on Tiny Tapeout `clk` |
| Internal quadrature switching | 4 MHz | Four 50%-duty phase waveforms |
| Analog element input | 5 MHz | Validated low-IF operating point |
| Differential beam output | 1 MHz | Difference product of 5 MHz input and 4 MHz switching |
| Analog input amplitude | Up to 50 mV peak, bounded test | Worst observed compression 0.138 dB |
| Intended output receiver | High impedance, about 10 pF class | Not a direct 50-ohm driver |

For a 10.5 GHz antenna system, use an external four-channel RF front end. Each
path needs comparable filtering, gain, and an LO-coherent mixer to translate
10.5 GHz to the validated 5 MHz IF. Preserve relative phase through the four
RF/LO/IF paths. The V3 chip then performs the four-channel weighting and sum.

## 4. Pin description

### 4.1 Supplies and common wrapper controls

| Pin | Direction | Function |
|---|---|---|
| `VDPWR` | Supply | 1.8 V analog and digital supply |
| `VGND` | Supply | Ground return |
| `clk` | Input | Nominal 16 MHz master clock |
| `rst_n` | Input | Asynchronous active-low controller reset |
| `ena` | Input | Synchronized beamformer enable |

There is no separate 3.3 V analog supply in this design. `VAPWR` is not used.

### 4.2 Direct digital controls

| Pin | Function |
|---|---|
| `ui[2:0]` | Automatic beam selection, 0 through 7 |
| `ui[3]` | `0`: automatic beam table; `1`: raw per-channel vector words |
| `ui[7:4]` | Channel enables CH3 through CH0 |

Direct controls pass through two synchronizer stages before affecting the
analog control. Updates occur at the safe quadrature boundary and blank the
mixers/tail enables for one 4 MHz period.

### 4.3 Serial raw-vector configuration

| Pin | Direction | Function |
|---|---|---|
| `uio[0]` | Input | `CFG_CLK` |
| `uio[1]` | Input | `CFG_DATA` |
| `uio[2]` | Input | `CFG_LATCH` |
| `uio[7:3]` | Input/unused | Physically isolated unused inputs |

Shift 32 bits LSB first. The packet is packed little-endian by channel:
CH0=`[7:0]`, CH1=`[15:8]`, CH2=`[23:16]`, CH3=`[31:24]`. Each channel byte is
four two-bit group codes in the order weight 1, 2, 4, 8.

`CFG_LATCH` must be asserted on a separate rising `CFG_CLK` edge after all 32
data bits have been shifted. Asserting it on the same edge as the last bit
would commit the previous 32-bit shift value. After the commit toggle crosses
to the 16 MHz clock domain, the controller applies the word only at a safe
quadrature boundary.

### 4.4 Analog interface

| Pin | Direction | Function |
|---|---|---|
| `ua[0]` | Analog input | Element input CH0 |
| `ua[1]` | Analog input | Element input CH1 |
| `ua[2]` | Analog input | Element input CH2 |
| `ua[3]` | Analog input | Element input CH3 |
| `ua[4]` | Analog output | Differential beam output P |
| `ua[5]` | Analog output | Differential beam output N |
| `ua[7:6]` | Unused | Intentionally isolated wrapper shapes |

All 24 digital output terminals (`uo_out`, `uio_out`, and `uio_oe`) are
physically tied to `VGND`, matching the Verilog boundary contract.

## 5. Automatic beam table

Automatic mode provides eight array coefficient sets. The low byte is CH0.

| Beam | Packed 32-bit word |
|---:|---:|
| 0 | `0x08080808` |
| 1 | `0xBFF7C008` |
| 2 | `0x5DA2F708` |
| 3 | `0xC05DBF08` |
| 4 | `0xA208A208` |
| 5 | `0x15F76A08` |
| 6 | `0xF7A25D08` |
| 7 | `0x6A5D1508` |

The eight single-channel phase words used by the architecture model are:

| Target state | Word | Ideal modeled phase |
|---:|---:|---:|
| 0 | `0x08` | 0 degrees |
| 1 | `0x15` | 41.186 degrees |
| 2 | `0x5D` | 90 degrees |
| 3 | `0x6A` | 131.186 degrees |
| 4 | `0xA2` | 180 degrees |
| 5 | `0xBF` | 221.186 degrees |
| 6 | `0xF7` | 270 degrees |
| 7 | `0xC0` | 311.186 degrees |

The ideal eight-state magnitude span is 0.297 dB and the largest ideal phase
quantization error is 3.814 degrees. Raw mode exposes all 256 possible words
per channel for calibration or experimental weighting.

## 6. Power-on and safe operating sequence

The recommended sequence is:

1. Hold `rst_n=0` and `ena=0` while the 1.8 V supply rises.
2. Keep the analog inputs within the supply rails and avoid driving the output.
3. Wait at least 60 us after `VDPWR` is stable.
4. Apply a stable 16 MHz `clk` and stable control inputs.
5. Release `rst_n`.
6. Program raw coefficients if required, or select an automatic beam.
7. Assert the desired channel-enable bits and `ena`.
8. Discard at least 2 us of output after a code update; use a longer board-level
   acquisition delay if external AC coupling or high capacitance is present.

The 60 us startup delay is intentionally conservative and is tied to the
bounded startup sweep recorded in `v3/evidence/four_channel_startup.json`.

The completed factorized startup matrix covered all five MOS/VDD/temperature
corners in the reference beam mode plus all four vector-mode classes at TT:

| Startup measurement | Worst observed | Acceptance limit |
|---|---:|---:|
| VCM reaches 90% | 19.235 us | 25 us |
| VCM remains within 2% of final value | 49.011 us | 60 us |
| VBIAS reaches 90% | 0.0478 us | 5 us |
| Output common mode crosses 0.8 V | 0.0554 us | 5 us |
| Output common mode remains within 2% | 17.011 us | 20 us |
| Final VCM divider-target error | 0.1396% | 1% |

The output-node limit is subordinate to the slower VCM divider. No functional
enable is permitted until the full 60 us startup interval has elapsed.

## 7. Electrical characteristics from simulation

Unless stated otherwise, results are schematic or extracted-layout simulation
results, not guaranteed production measurements.

### 7.1 Architecture, phase, and calibration

| Characteristic | Result |
|---|---:|
| Guaranteed phase states | 8 |
| Raw words per channel | 256 |
| Unit slices per channel | 15 |
| Ideal magnitude span | 0.297 dB |
| Worst ideal phase error | 3.814 degrees |
| Mismatch screen | 16 independently calibrated device realizations |
| Worst validated mismatch phase error | 4.356 degrees |
| Worst validated mismatch gain span | 0.408 dB |
| Minimum mismatch-run output common mode | 1.574 V |

Mismatch calibration and validation used separate input amplitudes and SPICE
decks on each fixed device realization. The selected codebook for a die was
frozen before its validation run. This is a bounded engineering screen, not a
foundry-qualified Monte Carlo yield estimate; passive mismatch, systematic
gradients, package variation, measurement noise, and drift are not included.

### 7.2 PVT, current, and common mode

The selected support circuit uses 2.925 kohm differential load resistors, three
MIM units in the VCM network, no varactor, and a divider scaled to 0.25 of the
V2 implementation. Twenty cases cover four beam-mode classes at five bounded
MOS/VDD/temperature corners.

| Characteristic | Bounded result |
|---|---:|
| Supply range used in PVT | 1.62 V to 1.98 V |
| Analog/support supply current | 0.4165 mA to 0.5377 mA |
| Analog/support power | 0.675 mW to 1.065 mW |
| Lowest average output common mode | 1.195 V |
| Lowest instantaneous output common mode | 1.1948 V |
| Maximum VCM ripple | 11.335 mV peak-to-peak |

The current/power figures cover the simulated four-channel analog/support
network and do not claim total Tiny Tapeout controller/package consumption.

### 7.3 Linearity and load sensitivity

| Test | Result |
|---|---:|
| Worst compression at 20 mV peak input | 0.021 dB |
| Worst compression at 50 mV peak input | 0.138 dB |
| Gain loss with 30 pF per output pad | 2.655 dB |
| Gain loss with 60 pF per output pad | 6.709 dB |

The capacitance here is everything loading each output pad: pad/package,
board trace, probe, cable, receiver input, and any intentional capacitor. It is
not a programmable on-chip setting. Use a short route to a high-impedance,
low-capacitance differential receiver. A 50-ohm instrument requires an
external buffer or a later on-chip output-driver architecture.

### 7.4 Switching, spurs, and noise

| Characteristic | Result |
|---|---:|
| Ordered code transitions tested | 56 |
| Mixer blanking interval | 250 ns |
| Maximum bounded post-update settling | 2 us |
| Raw square-wave mixer spur | -9.736 dBc |
| Worst spur after defined 2 MHz two-pole receiver | -34.345 dBc |
| Conservative output-noise estimate, 10 Hz to 2 MHz | 48.01 uV RMS |
| Minimum nominal SNR at 5 mV peak input | 38.61 dB |

The open-source noise gate uses a driven transient-noise equivalent crosscheck,
not native periodic-noise analysis. It includes switched intrinsic device
noise in the schematic channel but excludes clock-source phase noise,
extracted-layout noise modulation, package/board noise, and silicon correlation.

### 7.5 Extracted distributed-RC matching

| Extracted metric | Result |
|---|---:|
| Four-input route-resistance mismatch | 0% in extracted vectors |
| Input external-capacitance span | 1.889% |
| Estimated input gain spread at 5 MHz, 1 kohm source | 0.00000087 dB |
| Estimated input phase spread at 5 MHz, 1 kohm source | 0.002485 degrees |
| Output effective-capacitance mismatch | 0.1852% |
| Output estimated time-constant mismatch | 0.1652% |
| Output estimated differential phase error at 5 MHz | 0.003151 degrees |

These results include distributed metal resistance and extracted capacitance
for the routed input and output paths. They do not include package or PCB
parasitics; those must be added in the carrier-board model.

## 8. External circuit recommendations

### 8.1 Four-channel RF-to-IF front end

For 10.5 GHz operation, use four closely matched external paths:

1. Antenna and ESD/RF connector structure.
2. 10.5 GHz band-pass filter and optional LNA.
3. Four mixers driven from a common low-phase-noise LO distribution.
4. IF filtering centered at 5 MHz with matched group delay.
5. Bias/level shifting so each `ua[0:3]` waveform remains within the 1.8 V
   input operating range and presents approximately equal source impedance.
6. Short, symmetric connections into `ua[0:3]`.

Gain mismatch can be partly corrected by raw vector codes; arbitrary frequency-
dependent phase or group-delay mismatch cannot. Characterize the complete four
path RF/LO/IF assembly and calibrate it as a system.

### 8.2 Differential output connection

Connect `ua[4]` and `ua[5]` to a high-input-impedance differential amplifier or
ADC driver. Keep total capacitance close to the validated 10 pF class. If AC
coupling is required, choose equal capacitors and bias both receiver inputs to
the same common-mode voltage. Do not connect either output directly to 50 ohms.

### 8.3 Decoupling and clock quality

Place local 1.8 V decoupling close to the carrier. The digital 16 MHz clock
generates the mixer quadrature; clock duty cycle, edge timing, and phase noise
therefore affect beam phase and reciprocal mixing. Use one clean clock source
and avoid routing it beside the analog input/output traces on the test board.

## 9. First-silicon test procedure

1. Verify resistance to ground/supply with the board unpowered and no analog
   source connected.
2. Current-limit the 1.8 V supply and confirm startup current is plausible.
3. Follow the 60 us power-on wait, then enable one channel at a time.
4. Drive a small 5 MHz tone, initially 5 mV peak, through four equal source
   networks.
5. Observe the 1 MHz differential output using a high-impedance low-capacitance
   receiver.
6. Confirm all eight automatic states and record gain, phase, common mode,
   current, and settling.
7. Enter raw mode, calibrate the eight desired phase states independently for
   each channel, and freeze that die's codebook.
8. Validate the frozen codebook with a separate stimulus level and data set.
9. Sweep input amplitude up to 50 mV peak and output loading only after the
   low-level behavior is established.
10. Repeat across supply and temperature before attaching the 10.5 GHz RF
    front end.

## 10. Validation and fabrication gates

The exact frozen GDS has:

- zero pinned direct-GDS FEOL, BEOL, off-grid, zero-area, pin-purpose, and
  project-flat markers;
- zero Magic hierarchical and flat DRC markers;
- 6,037 extracted devices with the expected model population;
- all six used analog pins connected and `ua[7:6]` isolated;
- all 24 digital outputs physically grounded;
- separate `VDPWR` and `VGND` extracted networks;
- an exact 53-port GDS/LEF wrapper contract;
- a full 334.88 um x 225.76 um Tiny Tapeout project boundary; and
- independent flattened topology and interface-connectivity audits.

The official Tiny Tapeout custom-GDS, viewer, precheck, and artifact-bound
validation jobs passed on this exact published SHA-256 in workflow run
`30341656935`. Any geometry change after that point invalidates the hash-bound
physical, RC, and external evidence and must be assessed through the
hierarchical change policy.

## 11. Evidence map

| Evidence | File |
|---|---|
| Consolidated release gate | `v3/evidence/submission_gate.json` |
| Power-on startup | `v3/evidence/four_channel_startup.json` |
| Architecture / mismatch / linearity / switching | `v3/evidence/implementation_checkpoint.json` |
| Support-network PVT | `v3/evidence/four_channel_support_pvt.json` |
| Periodic-noise equivalent | `v3/evidence/periodic_noise_summary.json` |
| Output distributed RC | `v3/evidence/four_channel_output_load_rc.json` |
| Input distributed RC | `v3/frozen/analog_input_escapes/input_rc_audit.json` |
| Official-wrapper mirror | `v3/frozen/submission/official_contract.json` |
| Official GitHub attestation | `v3/frozen/submission/github_attestation.json` |
| Flattened topology | `v3/frozen/submission/topology_audit.json` |
| Direct-GDS precheck | `v3/frozen/submission/direct_precheck/precheck_summary.json` |
| Visual review views | `v3/frozen/submission/review/` |

## 12. Known limitations

- This is a receive-only low-IF beamformer, not a transmit driver and not a
  direct 10.5 GHz phase shifter.
- The unbuffered output cannot directly drive a 50-ohm load.
- Package, PCB, antenna, RF mixer/LNA, and external LO behavior are not in the
  extracted chip simulations.
- Open-source transient-noise equivalence is not a replacement for native PSS/
  PNoise or silicon noise measurement.
- The bounded mismatch campaign is not a foundry-qualified yield prediction.
- ESD, package limits, absolute-maximum ratings, and final test-board limits are
  governed by the selected Tiny Tapeout carrier and must be confirmed against
  its official documentation before lab use.
