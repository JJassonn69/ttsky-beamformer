# Beamformer V2 electrical and architecture specification

Status: frozen V2A architecture contract with a locally validated physical
routing candidate. This file is not a silicon signoff claim.

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
- The selected local topology uses two shared first-stage 2:1 muxes, matched
  P/N final muxes with swapped A/B inputs, matched blanking gates, and matched
  output buffers from the pinned official SKY130 HD library.
- Beam and manual-phase changes must be committed on a defined safe clock
  boundary.
- Use break-before-make selection or blank the mixers for one LO period during
  a phase update.
- A 30 MHz LO would require a nominal 120 MHz phase-generator clock and is a
  separate stretch target, not a V2A rating.

The local selector itself passed its current schematic-level 4 and 30 MHz PVT
sweep with less than 8 ps worst P/N skew. This does not promote V2A to a 30 MHz
LO rating: the master-clock generator, global phase tree, mixer, package, and
extracted interconnect must independently close at 120/30 MHz.

## Channel-gain calibration

V2A uses one four-bit, channel-local switched tail-current bank per channel.
It does not route an analog DAC voltage across the macro. Every current-source
finger is the same 1.26 by 0.50 um NMOS unit. Forty-two units are always on;
binary groups of 1, 2, 4, and 8 units are selected by the trim code. Code 8
therefore enables 50 units and is the nominal point.

Verified schematic-level tail-current behavior:

- four-bit unsigned code, default code 8;
- relative current from 0.84 at code 0 through 1.00 at code 8 to 1.14 at code
  15;
- monotonic in all 27 combinations of TT/FF/SS, 1.62/1.80/1.98 V, and
  -40/27/85 C;
- worst endpoint-fit DNL and INL below 0.00047 LSB in that deterministic PVT
  sweep;
- static codes during beam measurements; and
- code changes committed while the channel is blanked.

The fixed bank is physically split into three identical 14-finger groups.
The binary groups use the same unit finger geometry and remain inside the
owning channel guard ring. Extraction must recover 57 equal current fingers,
not four unrelated transistor widths.

The R-2R study remains in `v2/spice/r2r_4bit.inc` as characterized research.
The standalone ladder was monotonic across the exercised PVT and load sweep,
but a passive tail-bias blend measurably pulled the shared bias. Buffering four
DAC voltages would add offset, power, area, and long analog control routes.
For those reasons, R-2R is excluded from the V2A production floorplan. It is
better suited to a future standalone voltage control, vector modulator, or
programmable common-mode reference.

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

A 24-bit serial configuration chain carries exactly:

- four two-bit manual phase codes; and
- four four-bit gain-trim codes.

The frozen integration mapping uses `uio_in[0]` for configuration clock,
`uio_in[1]` for configuration data, and `uio_in[2]` for the atomic
configuration latch. The 24-bit packet is shifted LSB-first: trim bits
`trim[15:0]` first, followed by manual phase bits `manual_phase[7:0]`. The
latch is asserted for one separate configuration-clock edge after shifting;
a toggle synchronizer carries the commit into the master-clock domain. Direct
controls pass through two flip-flops. Both paths are applied only at the
defined phase-state boundary and blank all channels for one complete LO
period. Reset selects zero-degree manual phase, trim code 8 on all channels,
and disables every channel. All unused outputs remain static to minimize
digital-to-analog coupling. The final TinyTapeout wrapper still has to bind
this contract to the submission template.

## Physical architecture contract

- Initial area target: SKY130A 2x2 analog macro.
- Place four identical narrow channel slices directly above `ua[0:3]`, on the
  exact 19.32 um analog-pin pitch.  This translational symmetry avoids four
  unequal lateral input runs; the shared differential loads and clock tree are
  centered on the channel array rather than on the otherwise mostly empty die.
- Give every channel identical device composition, orientation, local escape,
  phase mux, switched-tail bank, and clock loading.
- Match all four input-pin-to-transconductor routes and independently match
  the two output routes.
- Extend the V1 no-floating-stub, via-ownership, capacitor-keepout, clean-route
  regeneration, and distributed-RC gates to every V2 net.
- The four phase-tree leaves must match electrically after extracted RC; equal
  drawn Manhattan length alone is insufficient.
- Treat phase nets as noise sources: shield them from inputs, static trim
  controls, the output load, and shared bias circuitry.
- Keep the shared summing node short and centered. A long common bus is not an
  acceptable substitute for symmetric placement.

The active numerical route and parasitic gates are frozen in
`control_openroad_route_plan.json`, `control_routing_checkpoint.json`, and the
associated extraction audits. Analog performance limits remain provisional
until the frozen distributed-RC view completes the post-layout sensitivity
sweep.

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

- Clock-buffer sizing for any frequency target beyond the nominal 16 MHz
  master clock.
- Final analog-performance acceptance of the selected ABBA channel ordering
  and R0/MY source-facing device pairs after post-layout mismatch simulation.
- Whether V2B uses a passive reciprocal mixer or separate active TX/RX paths.
- Whether calibrated coefficients are loaded externally on every power-up or
  stored by the test controller.

These items require simulation or a physical placement study and must not be
settled by layout convenience alone.
