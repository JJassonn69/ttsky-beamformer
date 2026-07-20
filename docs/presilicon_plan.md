# Pre-silicon verification plan

The six-to-seven-month fabrication cycle makes first-silicon debugging an
unacceptable substitute for simulation. Results are generated from scripted
netlists with machine-readable pass/fail limits; fabrication compatibility and
electrical confidence are tracked separately.

## Completed for the iteration-one release candidate

- dependency-free phasor golden model and phase sweep;
- ideal architecture and modeled TinyTapeout analog paths;
- transistor-level SKY130 bias, common-mode generator, complementary LO
  buffers, two transconductors, two commutating mixers, analog phase selector,
  matched output loads, PDK resistors, and MIM capacitor;
- schematic 45-case deterministic PVT grid: TT/SS/FF/SF/FS, 1.62/1.80/1.98 V,
  and -40/27/125 C;
- exact 1x2 TinyTapeout boundary with 70 PCells and explicit M2/M3/M4 routing;
- split A/B; B/A common-centroid channel devices, mirrored passives, matched
  local breakouts, and a full MIM route keep-out;
- zero Magic errors at placement, routed, extraction, and final DRC stages;
- extraction topology check: 338 MOS fingers, eight passives, connected power,
  and no unexpected net equivalences;
- zero Magic GDS-writer geometry warnings;
- flattened emitted-GDS regression: zero M3/M4 spacing, M4 connected-area,
  and capm-clearance markers; the checker reproduced the original independent
  precheck's 9/12/176/2 marker counts before the route fix;
- paired, equal-settling-time full-parasitic sum/null simulation;
- coherent extracted 4/10/20/30 MHz LO sweep: 4/4 pass the 20 dB release gate,
  with 51.83 dB null at 4 MHz and 33.93 dB at 30 MHz;
- extracted LO rail/edge/skew sweep: 4/4 pass through 30 MHz;
- nominal extracted channel amplitude difference: 0.0000374 percent;
- foundry-slope mismatch surrogate: 30/30 pass, 39.28 dB worst null;
- parasitic-extracted deterministic PVT: 45/45 pass, 25.60 dB worst null at
  FF, 1.62 V, and 125 C; and
- the locally runnable official TinyTapeout structural, pin, boundary, power,
  layer, analog-pad, cell-name, and Verilog checks.

The PVT release gate follows `spec/beamformer_v1.md`: at least 20 dB destructive
null at every deterministic corner. The nominal test keeps a stronger 40 dB
implementation target. Reports also preserve the actual null depth so a passed
threshold cannot hide lost margin.

## Deliberately limited first-silicon scope

This macro is an always-on binary 0/180-degree combiner. It does not implement
shutdown, per-channel enables, gain control, calibration storage, or multi-bit
phase weights. `ena` and `rst_n` exist for wrapper compatibility but are not
connected to the analog core. The chip has no 50-ohm input match, LNA,
inductor, transformer, transmission-line phase shifter, or large IF filter.

## Remaining electrical confidence work before paying for fabrication

- replace the ngspice foundry-slope mismatch surrogate with native
  foundry-qualified Spectre Monte Carlo and a larger documented sample count;
- sweep independent input series resistance and shunt capacitance, package and
  pad capacitance, output load from 0 to 10 pF, source amplitude, LO duty cycle,
  and relative startup phase;
- characterize noise, input compression, two-tone IM3, LO feedthrough, unwanted
  mixer products, phase-select transient, and supply sensitivity;
- perform an independent LVS with a second tool if available; the current
  extraction checker is topology-aware but is not a foundry-qualified LVS
  replacement;
- review antenna and density behavior in the assembled shuttle context; and
- confirm the shuttle's actual analog pad/ESD parasitics and safe drive limits.

No item above is silently converted into a fabrication pass. If the first run
is submitted before those close, it should be treated as a learning vehicle,
not a production RF component.

## GitHub/TinyTapeout release gate

The repository uses the official `ttsky26c` custom-GDS, precheck, viewer, and
documentation actions. A release is mechanically submission-ready only when:

1. the `gds` artifact job passes;
2. TinyTapeout precheck passes every Magic and KLayout rule and every pin,
   boundary, layer, power, analog-pad, cell-name, and Verilog check;
3. the documentation job passes;
4. the published artifact contains the expected uncompressed GDS, LEF,
   Verilog, `info.yaml`, docs, license, PDK metadata, and commit metadata; and
5. the hashes in `submission/template.lock` match the committed views.

## Silicon bench rehearsal

Before delivery, prepare two phase-locked and independently phase-adjustable
5 MHz sources, a 0-to-1.8 V 4 MHz clock, input AC-coupling, a high-impedance
differential receiver, and an external approximately 2 MHz low-pass filter.
Automate a 360-degree input phase sweep and record constructive amplitude,
null depth, output common mode, current, and safe pin voltages. Do not terminate
the analog outputs directly in 50 ohms.

After nominal 4 MHz bring-up succeeds, repeat with 10, 20, and 30 MHz LO and
set each input to `LO + 1 MHz`. Treat these as characterization modes until pad,
package, board, temperature, supply, and mismatch data support an operating
rating.
