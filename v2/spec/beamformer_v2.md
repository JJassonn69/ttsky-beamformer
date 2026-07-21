# Beamformer V2 electrical and architecture specification

Status: architecture baseline. This file is not a silicon signoff claim.

## Objective

Extend the V1 two-channel binary receive beamformer to four matched channels
and four orthogonal narrowband beam states. Preserve the proven 5 MHz input,
4 MHz LO, and 1 MHz output signal plan for the first V2 silicon target.

The implementation must support independent channel characterization and
static gain calibration. Its external analog pin assignment is chosen so a
future reciprocal or switched TX/RX implementation can reuse the same package
interface without redefining the element ports.

## Release staging

### V2A release target

An active four-channel receive beamformer:

- four single-ended, AC-coupled, phase-coherent 5 MHz element inputs;
- one differential, high-impedance 1 MHz beamformed output;
- a digitally generated 4 MHz quadrature LO from a nominal 16 MHz master
  clock;
- four selectable DFT beam states;
- manual two-bit phase control per channel;
- independent channel enable; and
- independent static four-bit gain trim per channel.

### V2B research target

Bidirectional operation using the same four element ports and common
differential port. V2B is not part of the V2A release requirement. It must
first prove conversion loss or gain, port impedance, TX/RX isolation, LO
feedthrough, linearity, direction switching, and package sensitivity in
schematic and extracted simulation.

The inherited active V1 transconductor/mixer is directional. It must not be
described or tested as reciprocal.

## Analog pin contract

| Pin | V2A receive function | Reserved bidirectional function |
| --- | --- | --- |
| `ua[0]` | element input 0 | RX input 0 / TX output 0 |
| `ua[1]` | element input 1 | RX input 1 / TX output 1 |
| `ua[2]` | element input 2 | RX input 2 / TX output 2 |
| `ua[3]` | element input 3 | RX input 3 / TX output 3 |
| `ua[4]` | combined output P | RX output P / TX input P |
| `ua[5]` | combined output N | RX output N / TX input N |

All ports remain low-current, high-impedance signal ports. No on-chip 50-ohm
match, PA, LNA, transformer, or antenna interface is implied.

## Beam codebook

For channel index `n` and beam index `b`, the transmit reference phase is:

`phase_tx(n, b) = 90 degrees * ((n * b) mod 4)`.

Receive combining applies the complex-conjugate weight:

`phase_rx(n, b) = -phase_tx(n, b)`.

| Beam | CH0 | CH1 | CH2 | CH3 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 0 deg | 0 deg | 0 deg | 0 deg |
| 1 | 0 deg | 90 deg | 180 deg | 270 deg |
| 2 | 0 deg | 180 deg | 0 deg | 180 deg |
| 3 | 0 deg | 270 deg | 180 deg | 90 deg |

The four ideal codebook vectors are orthogonal. Exact cancellation applies to
the other three ideal vectors with equal channel amplitude and phase, not to
every continuous physical arrival angle. Continuous-angle simulations must
report the main lobe, sidelobes, and any grating lobes separately.

## Phase generation and switching

- Nominal master clock: 16 MHz.
- Nominal quadrature LO: 4 MHz.
- Generate 0, 90, 180, and 270 degree phases with a resettable divide-by-four
  digital phase generator.
- Distribute the four phases through a balanced, shielded tree.
- Every channel must contain the same phase-select topology and load all four
  phase lines equally.
- Beam and manual-phase changes must be committed on a defined safe clock
  boundary.
- Use break-before-make selection or blank the mixers for one LO period during
  a phase update.
- A 30 MHz LO would require a nominal 120 MHz phase-generator clock and is a
  separate stretch target, not a V2A rating.

## R-2R calibration DACs

V2A contains one four-bit trim DAC per channel. The DAC output controls a
high-impedance gain-setting or bias-control node through a buffer or otherwise
proven isolation stage.

The R-2R ladder must not carry the 5 MHz signal directly in V2A.

Provisional targets, subject to transistor-level and Monte Carlo refinement:

- four-bit unsigned code, default code 8;
- approximately 0.85 to 1.15 relative channel-gain range;
- monotonic response across selected PVT corners;
- static codes during beam measurements;
- code updates performed while the affected channel is muted;
- identical unit resistors for `R`, with `2R` made from two series units;
- dummy units, common orientation, matched driver resistance, and symmetric
  local routing; and
- local supply filtering and physical separation from the quadrature clock.

DAC calibration is allowed to improve typical and measured nulls. The
uncalibrated beamformer must still meet its separately stated release floor.

## Digital control contract

Direct controls:

| Signal | Function |
| --- | --- |
| `ui_in[1:0]` | automatic beam index 0 through 3 |
| `ui_in[2]` | reserved TX/RX direction; RX for V2A |
| `ui_in[3]` | automatic codebook / manual phase mode |
| `ui_in[7:4]` | channel-enable mask |
| `ena` | global analog and clock enable |
| `rst_n` | phase generator and configuration reset |

A serial configuration register will carry at least:

- four two-bit manual phase codes; and
- four four-bit gain-trim codes.

Candidate pins are `uio[0]` configuration clock, `uio[1]` configuration data,
and `uio[2]` atomic configuration latch. The final crossing and reset behavior
must be specified before RTL is frozen. All unused outputs remain static to
minimize digital-to-analog coupling.

## Physical architecture contract

- Initial area target: SKY130A 2x2 analog macro.
- Place four channel cores in a fourfold-symmetric arrangement around the
  centered output load, bias, and clock distribution.
- Give every channel identical device composition, orientation, local escape,
  phase mux, DAC buffer, and clock loading.
- Match all four input-pin-to-transconductor routes and independently match
  the two output routes.
- Extend the V1 no-floating-stub, via-ownership, capacitor-keepout, clean-route
  regeneration, and distributed-RC gates to every V2 net.
- The four phase-tree leaves must match electrically after extracted RC; equal
  drawn Manhattan length alone is insufficient.
- Treat phase nets as noise sources: shield them from inputs, gain controls,
  the output load, and R-2R ladders.
- Keep the shared summing node short and centered. A long common bus is not an
  acceptable substitute for symmetric placement.

Numerical route, skew, and parasitic tolerances will be frozen only after the
first placement study and extracted sensitivity sweep.

## Verification gates

1. Golden complex-vector model proves all 16 transmit-code/receive-selection
   combinations and manual-phase behavior.
2. System model sweeps continuous angle, gain error, phase error, path RC, and
   four independent trim codes.
3. Quadrature generator proves phase order, non-overlap, reset behavior, duty
   cycle, and switching at relevant clock corners.
4. One channel proves gain, noise, linearity, phase, trim range, trim
   monotonicity, settling, and code-glitch behavior in transistor-level SPICE.
5. Four-channel schematic proves constructive gain and off-beam rejection for
   all four beams over PVT.
6. Monte Carlo reports uncalibrated yield and recalibrated yield without
   optimizing and measuring against the same noise sample.
7. Layout passes Magic DRC, extraction topology, independent LVS when
   available, direct-GDS flat checks, route constraints, and zero-stub audits.
8. Full distributed-RC extraction includes devices, capacitance, and metal
   resistance on every electrical net.
9. Post-layout simulation repeats the complete 4x4 codebook, calibration,
   independent pad parasitics, and clock-coupling tests.
10. V2 release evidence and datasheet are generated from the frozen GDS hash
    and attested by the official GitHub workflow.

## Decisions intentionally left open

- Exact R-2R unit resistance and trim-to-transconductance transfer.
- Quadrature generator logic family and clock-buffer sizing.
- V2A channel common-centroid ordering and permitted device rotations.
- Whether V2B uses a passive reciprocal mixer or separate active TX/RX paths.
- Whether calibrated coefficients are loaded externally on every power-up or
  stored by the test controller.

These items require simulation or a physical placement study and must not be
settled by layout convenience alone.
