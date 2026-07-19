# TT-BF1 two-channel low-IF beamformer

Engineering datasheet and iteration handoff, release candidate 1.0

Target: TinyTapeout SKY130 `ttsky26c`

Top macro: `tt_um_jjassonn69_beamformer`

Date: 2026-07-19

## 1. Document purpose and status

This document records what was designed, why the architecture was chosen, how
the implementation was produced, what has actually been verified, and what is
still unknown. It is both the first-silicon datasheet and the starting context
for the next beamformer iteration.

The design is a pre-silicon release candidate. Values labeled *simulated* are
not production guarantees. No packaged silicon has been measured yet, and the
shuttle pad, ESD, package, board, mismatch, noise, and linearity behavior is not
fully characterized. Do not infer absolute-maximum ratings from the simulated
PVT envelope.

## 2. Product summary

TT-BF1 is a two-channel, binary-weight, narrowband receive beamformer for
phase-coherent 5 MHz intermediate-frequency inputs. A shared 4 MHz local
oscillator commutates both channel currents. Channel 2 can use the normal or
exchanged LO polarity, providing a selectable 0- or 180-degree weight. The
channel currents sum into a differential resistive load, and the useful 1 MHz
difference-frequency output is selected by an external low-pass filter.

The first iteration deliberately solves the smallest useful on-chip problem:
coherent two-channel combining and cancellation. Input impedance matching, an
LNA, antenna interface, RF phase shifting, and the final output filter remain
off-chip. This keeps the experiment within one 1x2 analog tile and avoids
making package- and board-dependent RF structures before their parasitics are
known.

### Key features

- two phase-coherent, AC-coupled, high-impedance 5 MHz inputs;
- differential 1 MHz beamformed output from a 4 MHz LO;
- binary 0/180-degree weight on channel 2;
- on-chip complementary LO generation and phase selection;
- shared on-chip bias, input common mode, resistive output load, and MIM
  decoupling;
- nominal 1.8 V operation using `VDPWR`; no `VAPWR` dependency;
- 161.00 x 225.76 um 1x2 TinyTapeout analog macro;
- 47 placed SKY130 PCells and 239 extracted MOS fingers;
- committed uncompressed GDSII and exact-template LEF; and
- reproducible golden, schematic-SPICE, extracted-SPICE, PVT, physical, and
  release-integrity checks.

## 3. Functional block diagram

```text
 IF_INPUT_1 -> AC coupling -> bias/GM1 -> commutating mixer 1 ---+
                                                               |
                                                               +-> shared
 IF_INPUT_2 -> AC coupling -> bias/GM2 -> commutating mixer 2 ---+   differential
                                      ^                            load
                                      |
                                  0/180 LO mux                 BEAM_OUT_P
                                      ^                       BEAM_OUT_N
                                      |
 clk 4 MHz -> complementary LO buffers + phase-select control
```

For equal-amplitude, equal-phase inputs, `CH2_PHASE_180=0` produces the
constructive sum. `CH2_PHASE_180=1` exchanges the channel-two LO rails and
produces the destructive null. This is phase inversion, not a true time delay,
so wideband array behavior is outside the v1 scope.

## 4. Pin description

| TinyTapeout pin | Datasheet name | Direction | Function |
|---|---|---:|---|
| `VDPWR` | 1V8_SUPPLY | power | Nominal 1.8 V analog and logic supply. |
| `VGND` | GROUND | power | Supply and signal reference. |
| `clk` | LO_CLK | input | 0-to-`VDPWR`, nominal 4 MHz square-wave LO input. |
| `ui_in[0]` | CH2_PHASE_180 | input | Low: constructive 0-degree channel-two weight. High: inverted 180-degree weight. |
| `ui_in[7:1]` | RESERVED | input | No analog-core function in v1. |
| `ua[0]` | IF_INPUT_1 | analog input | AC-coupled, high-impedance channel-one input. |
| `ua[1]` | IF_INPUT_2 | analog input | AC-coupled, high-impedance channel-two input. |
| `ua[2]` | BEAM_OUT_P | analog output | Positive beamformed output. Use a high-impedance receiver. |
| `ua[3]` | BEAM_OUT_N | analog output | Negative beamformed output. Use a high-impedance receiver. |
| `ua[5:4]` | UNUSED_ANALOG | analog | Not connected by the project macro. |
| `ua[7:6]` | RESERVED_BOUNDARY | analog boundary | Not used by the project. |
| `ena` | RESERVED_ENABLE | input | Boundary-compatible only; the v1 analog core is always active when powered. |
| `rst_n` | RESERVED_RESET | input | Boundary-compatible only; no v1 analog reset function. |
| `uo_out[7:0]` | UNUSED_OUTPUTS | output | Tied low in the wrapper. |
| `uio_out[7:0]` | UNUSED_BIDIR_OUT | output | Tied low in the wrapper. |
| `uio_oe[7:0]` | UNUSED_BIDIR_OE | output | Tied low; bidirectional digital pins remain inputs. |

### Phase-select truth table

| `CH2_PHASE_180` | Channel-two weight | Equal-phase input result |
|---:|---:|---|
| 0 | 0 degrees | Constructive sum |
| 1 | 180 degrees | Destructive null |

The select input is static CMOS control. Avoid changing it during a precision
measurement until phase-select transient behavior is characterized.

## 5. Recommended operating conditions

These are intended operating conditions for the first bench experiment, not
foundry absolute-maximum ratings.

| Parameter | Recommended value | Verification envelope | Notes |
|---|---:|---:|---|
| `VDPWR` | 1.80 V | 1.62 to 1.98 V simulated | Use a quiet, current-limited supply. |
| Temperature | 27 C | -40 to 125 C simulated | Package behavior is not included. |
| LO frequency | 4 MHz | 4 MHz signoff point | 0-to-`VDPWR` square wave. |
| Input frequency | 5 MHz | 5 MHz signoff point | Two phase-locked sources. |
| Useful output | 1 MHz | 1 MHz signoff point | Difference product, measured differentially. |
| Input amplitude | 10 mVpp/channel | 10 to 30 mVpp intended | AC-coupled; compression is not yet characterized. |
| Input common mode | Internally biased | approximately 0.9 V design target | Do not externally force DC common mode. |
| Output load | high impedance | 1 Mohm fixture; 0 to 10 pF planned sweep | Never terminate either output directly in 50 ohms. |
| External LPF | approximately 2 MHz | two-pole simulation fixture | Required to reject higher mixer products. |

Every signal pin must remain between `VGND` and `VDPWR`. The actual shuttle
pad/ESD limits must be confirmed before connecting laboratory equipment.

## 6. Interface and impedance guidance

### Inputs

Each input is biased toward the shared on-chip common-mode node through an
approximately 100 kohm extra-high-resistance poly resistor. This makes the
interface high impedance at low IF, but the complete complex input impedance
also includes transistor, route, pad, ESD, package, and board capacitance. A
50-ohm match is therefore neither implemented nor claimed.

Drive each input through an AC-coupling capacitor from a phase-coherent source.
A bench source may retain its own 50-ohm source impedance; do not add a 50-ohm
shunt termination at the chip pin unless a separate attenuator or matching
network was intentionally designed for it.

### Why the 50-ohm match is off-chip

- the desired match depends on the package, pad, ESD, board, antenna, and test
  fixture rather than the core alone;
- a broadband resistive 50-ohm input would heavily load a small 1.8 V core;
- high-Q inductors, transformers, and transmission-line phase shifters are not
  efficient uses of a 1x2 SKY130 TinyTapeout tile; and
- an off-chip network can be changed after the actual silicon parasitics are
  measured.

For a later RF-facing version, measure the assembled input S-parameters first,
then co-design the external match or a dedicated on-chip LNA input stage.

### Outputs

The differential outputs are loaded on-chip by matched approximately 2.93
kohm high-resistance poly devices to `VDPWR`. Measure `BEAM_OUT_P -
BEAM_OUT_N` with a high-impedance differential probe or instrumentation
amplifier. Direct 50-ohm termination would collapse the intended gain and alter
the common mode.

## 7. Circuit architecture

### 7.1 Shared bias and common mode

A diode-connected 32 um/0.50 um NMOS and approximately 10.60 kohm poly
resistor generate the shared bias. Two approximately 100.15 kohm
extra-high-resistance poly devices generate the common-mode reference, which is
decoupled by a 22 x 22 um M3 MIM capacitor of approximately 0.983 pF.

### 7.2 Channel transconductors

Each channel uses a matched NMOS single-ended-to-differential transconductor:
two 8 um/0.30 um input devices and one 38 um/0.50 um tail device. One gate sees
the AC-coupled input and the other sees the common-mode reference.

### 7.3 Commutating mixers

Four 8 um/0.15 um NMOS switches per channel steer the transconductor currents
according to complementary LO rails. Both channels connect to the same
differential output load, so current summation is intrinsic rather than
implemented by a separate op-amp summer.

### 7.4 LO generation and binary phase weight

The single-ended `clk` input drives asymmetric multistage CMOS inverter paths
that generate buffered complementary rails. Four CMOS transmission gates select
normal or exchanged LO polarity for channel 2. Matched post-selector inverters
restore full swing and isolate the mixer-gate capacitance from the mux.

### 7.5 Passive inventory

| Function | Count | PDK device | Extracted/simulated nominal value |
|---|---:|---|---:|
| Output load | 2 | `res_high_po_1p41` | approximately 2.93 kohm each |
| Bias resistor | 1 | `res_high_po_1p41` | approximately 10.60 kohm |
| Input bias | 2 | `res_xhigh_po_1p41` | approximately 100.15 kohm each |
| VCM divider | 2 | `res_xhigh_po_1p41` | approximately 100.15 kohm each |
| VCM bypass | 1 | `cap_mim_m3_1` | approximately 0.983 pF |

All passives are predefined SKY130 PCells. Their physical geometry is generated
by the pinned open_pdks/Magic device generators rather than hand-drawn from
foundry layers.

## 8. Electrical simulation results

### 8.1 Nominal full-parasitic extracted result

Conditions: TT primitive models, 1.8 V, 27 C, 5 MHz equal-phase inputs, 4 MHz
LO, paired equal-settling-time sum/null simulations, and the external
measurement filter defined by the testbench.

| Measurement | Result | Release check |
|---|---:|---:|
| Constructive differential output | 14.7045 mVrms | greater than 1 mVrms |
| Destructive differential output | 0.109515 mVrms | used for null calculation |
| Destructive null | 42.5595 dB | greater than 40 dB nominal target |
| Output common mode, sum | 1.53876 V | 1.2 to 1.7 V nominal gate |
| Output common mode, null | 1.53875 V | 1.2 to 1.7 V nominal gate |
| Supply current, sum | 0.298042 mA | less than 1 mA |
| Supply current, null | 0.297806 mA | less than 1 mA |

### 8.2 Deterministic extracted PVT matrix

The full matrix covers TT, SS, FF, SF, and FS process corners; 1.62, 1.80, and
1.98 V supplies; and -40, 27, and 125 C temperatures. Each of the 45 cases
contains separate constructive and destructive simulations.

| Metric | Extracted PVT result |
|---|---:|
| Cases passed | 45/45 |
| Null release requirement | at least 20 dB at every corner |
| Minimum null | 29.0903 dB at FS, 1.62 V, -40 C |
| Maximum observed null | 50.0166 dB |
| Constructive output range | 4.03534 to 29.0855 mVrms |
| Output common-mode range | 1.35974 to 1.71545 V |
| Supply-current range | 0.126082 to 0.416378 mA |

The maximum PVT common mode occurs at the 1.98 V supply and is reported rather
than hidden by the pass gate. Use the committed JSON report for every case and
every individual check.

### 8.3 Schematic PVT and block results

- integrated schematic PVT: 45/45 cases pass, 52.1029 dB minimum null;
- ideal 1 dB gain/8 degree phase-error envelope: 20.3701 dB null;
- transistor mixer 1 dB/8 degree error envelope: 20.3721 dB null;
- LO rails: both highs above 1.75 V, lows below 50 mV nominal check, loaded
  edges below 2 ns, and path skew below 1 ns;
- bias reference: 105.198 uA nominal, with 2.03 percent mirror error at the
  low-headroom test point; and
- PDK passive smoke test: 2.933 kohm load, 10.603 kohm bias, 100.155 kohm
  extra-high resistor, and 0.983 pF MIM capacitor.

## 9. Physical implementation

| Item | Implemented value |
|---|---|
| Tile | official TinyTapeout 1x2 analog boundary |
| Macro size | 161.00 x 225.76 um |
| Placed PCells | 47: 39 MOSFETs, 7 resistors, 1 MIM capacitor |
| Extracted MOS fingers | 239 |
| Extracted passives | 8 |
| Signal routing | deterministic M2/M3/M4, 26 named tracks |
| Power | `VDPWR` and `VGND`; no `VAPWR` |
| GDS size | 651,370 bytes, uncompressed GDSII |
| GDS SHA-256 | `c445c59d2b2b98329c2daf885f9cafbbd8d5a63e46c33fbf474d20e294da8aaf` |
| LEF SHA-256 | `9df231957326895371afc1f5e903b51e7992b3b6f8c3401546fa7ef7d82eb760` |
| Official DEF SHA-256 | `042803101760925474f602e69119f497922eb912c37a6651bed030164bb576af` |

![Mask-layer rendering of the final beamformer GDS](images/beamformer-gds.png)

The figure is a KLayout mask-layer rendering of the committed GDSII stream,
not a microscope photograph of fabricated silicon.

## 10. Physical and submission verification

The following checks are complete for the committed local release candidate:

- Magic placement DRC: 0 errors;
- Magic routed-layout DRC: 0 errors;
- Magic extraction-stage DRC: 0 errors;
- Magic internal final signoff DRC: 0 errors;
- Magic GDS-writer geometry feedback: 0;
- official Magic readback DRC on the emitted GDS: 0 errors;
- extraction feedback: 0;
- extraction topology: 239 MOS fingers, 8 passives, power connected, and no
  unexpected net equivalences;
- official static prechecks: 8/8 locally runnable checks pass, covering top
  macro, forbidden layers, project boundary, exact DEF/LEF/GDS pin geometry,
  power pins, valid layers, cell names, analog-pad connectivity, and Verilog
  syntax; and
- release integrity: GDS/LEF hashes, plain GDSII header, macro dimensions, 53
  LEF pins, physical error counters, PVT result, and required metadata pass.

The GitHub workflow is the final mechanical submission gate because it also
runs the complete containerized TinyTapeout Magic and KLayout rule set. A green
workflow establishes compatibility with the pinned submission flow; it does
not guarantee analog performance or fabrication yield.

## 11. Tool and source provenance

| Component | Pinned revision/version |
|---|---|
| TinyTapeout analog template | `fdd487cb8e3003b40496f0f143ff3bf650f78e48` |
| TinyTapeout GDS action | `ttsky26c`, commit `30d38a7dfc6fda561d452b196fc822af0332ec23` |
| TinyTapeout support tools | `d65690eeb1d4afd26aef795c805a23d9d9daf9d1` |
| SKY130 precheck PDK | `0536d02d875c8f67dd7cca3902ac457e62f20005` |
| SKY130 primitive simulation models | `f62031a1be9aefe902d6d54cddd6f59b57627436` |
| Magic | 8.3.676 |
| KLayout precheck library | 0.30.8 |
| ngspice | 46 |

Only the sparse primitive model checkout is required for local schematic and
extracted simulation. The complete PDK is required for PCell generation,
extraction, and DRC. The external model checkout is intentionally excluded from
the repository and can be recreated from `third_party/README.md`.

## 12. Reproduction procedure

### Electrical verification

```sh
make verify
make pvt
make layout-sim
make layout-pvt
```

### Physical generation and signoff

With `PDK_ROOT` pointing to the pinned `sky130A` installation and `MAGIC_BIN`
set when Magic is not on `PATH`:

```sh
make layout-scripts
make layout-place
make layout-route
make layout-extract
make layout-signoff
make release-check
```

The deterministic source of physical intent is `layout/circuit.json` together
with the layout-script generators. The fabrication views are
`gds/tt_um_jjassonn69_beamformer.gds` and
`lef/tt_um_jjassonn69_beamformer.lef`. Machine-readable evidence is stored in
`submission/signoff.json`, `submission/core_pvt_summary.json`, and
`submission/extracted_pvt_summary.json`.

## 13. First-silicon bench procedure

### Required equipment

- current-limited, low-noise 1.8 V supply;
- two phase-locked, independently phase-adjustable 5 MHz sources;
- one 0-to-1.8 V 4 MHz clock source;
- two input AC-coupling networks;
- high-impedance differential probe or instrumentation receiver;
- approximately 2 MHz external low-pass filter; and
- automated acquisition capable of sweeping relative input phase.

### Bring-up sequence

1. Verify board continuity and the actual shuttle pinout with power removed.
2. Set the supply current limit conservatively and power `VDPWR` at 1.8 V.
3. Record quiescent current before applying input or clock signals.
4. Apply the 4 MHz LO and confirm supply current remains stable.
5. Apply one AC-coupled 5 MHz input at the minimum planned amplitude, then the
   second input.
6. With `CH2_PHASE_180=0`, adjust equal input phase and record the constructive
   1 MHz differential output after the external filter.
7. Set `CH2_PHASE_180=1` and record the destructive output without changing
   source amplitude.
8. Sweep channel-two phase through 360 degrees and save amplitude, phase,
   common mode, current, and raw spectra for both select states.
9. Repeat at safe supply, amplitude, output-capacitance, and temperature points
   only after the nominal result is understood.

### Measurements to preserve for iteration two

- per-channel gain and phase with the other input disabled externally;
- measured input impedance or S-parameters of the assembled pad/package/board;
- sum and null depth versus relative phase and amplitude;
- LO feedthrough and every visible mixer product;
- output common mode, available swing, and load sensitivity;
- supply current and supply pushing;
- noise spectrum, compression, two-tone IM3, and recovery after phase select;
  and
- die/board temperature and exact equipment calibration records.

## 14. Known limitations and open risks

1. Statistical mismatch/Monte Carlo has not been completed. Deterministic PVT
   does not predict random channel mismatch or null-yield distribution.
2. The present extraction topology checker is not a second, foundry-qualified
   LVS implementation.
3. Shuttle pad/ESD, package, bond-wire, and board parasitics are not included in
   the reported extracted simulations.
4. Noise, compression, IIP3, LO feedthrough, supply rejection, and phase-select
   transients have not passed a release characterization matrix.
5. Independent input path resistance and capacitance, output capacitance, LO
   duty cycle, source amplitude, and startup phase still require systematic
   sweeps.
6. Antenna and density behavior must be reviewed in the assembled shuttle
   context.
7. `ena` and `rst_n` do not shut down or reset the v1 analog core.
8. Binary phase inversion is useful for a narrowband demonstration but does not
   provide multi-angle steering or wideband true-time-delay behavior.

This silicon should therefore be treated as a learning and characterization
vehicle, not a production RF component.

## 15. Iteration-two recommendation

The most effective next architecture is an incremental extension of this same
low-IF current-summing core, not a jump directly to an on-chip RF front end.

### Recommended feature order

1. **Close v1 characterization:** complete mismatch Monte Carlo, package/pad
   sweeps, noise, compression, IM3, feedthrough, independent LVS, and the full
   automated bench rehearsal.
2. **Add real enable control:** use `ena` to shut down the bias and LO buffers;
   retain a defined output state during disable.
3. **Add per-channel observability:** provide a safe diagnostic mode that
   selects channel 1 only or channel 2 only, enabling direct gain/phase
   calibration.
4. **Add small gain trim:** a compact binary current or load trim can correct
   amplitude mismatch before finer phase control is attempted.
5. **Extend to four LO phases:** generate or accept 0/90/180/270-degree LO rails
   and select one per channel for a 2-bit phase beamformer. Keep the shared
   current-summing output and high-impedance low-IF interface.
6. **Add calibration storage/control:** use digital pins for phase and gain
   codes; avoid large analog control buses.
7. **Only then evaluate an RF-facing input stage:** use measured pad/package
   parasitics to choose an external match, on-chip LNA, or both. Do not assume
   50 ohms at the core gate.

### Layout lessons to retain

- use only validated SKY130 PCells for MOS, poly resistors, and MIM capacitors;
- preserve symmetric channel placement, equalized breakout geometry, and
  matched LO paths;
- maintain deterministic route generation and explicit overlap auditing;
- keep extraction feedback at zero before trusting extracted SPICE;
- reread the emitted GDS with the official DRC script rather than checking only
  the in-memory Magic layout; and
- hash every final view and machine-readable report before publication.

## 16. Handoff checklist

Before editing iteration two, archive or tag the green v1 commit and record:

- Git commit and GitHub Actions run URL;
- exact GDS, LEF, and report hashes;
- shuttle identifier and submitted artifact identifier;
- any action/PDK/template version changes since `ttsky26c`;
- all first-silicon raw data and bench scripts;
- measured parasitic model updates; and
- each spec change with an explicit reason and verification test.

When the next design starts, copy this document into the new revision and mark
each numerical table as unchanged, re-simulated, measured, or obsolete. That
prevents a passed v1 assumption from silently becoming an unverified v2
requirement.

## 17. Revision history

| Revision | Date | Description |
|---|---|---|
| RC1.0 | 2026-07-19 | Initial 1x2 binary 0/180-degree low-IF beamformer; GDS/LEF frozen, nominal extracted and 45-corner extracted PVT passing, local physical/release gates passing. |
