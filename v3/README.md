# Beamformer V3 workspace

## Current physical-design input

The only approved V3 channel macro is
`frozen/one_channel_macro/v3_channel_selector_late_promotion.gds`, with
SHA-256 `4cd2d39ba041ac80391516b35140ce79e476117fd4e73ae22795c565befbd274`.
`CURRENT.json` is the machine-readable authority. Run
`python3 v3/tools/assert_current_channel.py` before using a channel GDS in the
four-channel floorplan. Pilot, manual-canvas, and pre-late-promotion GDS files
are historical and must not be used as physical inputs.

Four immutable copies of this macro are now placed. Their differential output
collectors, four phase trees, balanced REF/VBIAS trees, exact VCM block,
complete tail-reference block, differential output loads, capacitance
compensation, direct output-pad escapes, one shared 1.8 V power/ground
network, the centralized static controller, all 41 internal
controller-to-analog handoffs, all 14 digital boundary handoffs, and four
matched analog-input pad escapes are integrated and hash-gated. All 24 unused
digital outputs are also physically tied low. The official TinyTapeout wrapper,
full project boundary, exact 53-port LEF/GDS contract, independent flattened
topology audit, and internal submission evidence are now complete. The
official GitHub custom-GDS, viewer, precheck, and artifact-bound validation
jobs are green for the exact frozen GDS hash.
The complete state before generated-artifact cleanup, including the manual
routing canvas, is recoverable from Git tag
`v3-one-channel-precleanup-20260727`. It is not an active design input.

## Four-channel placement gate

`layout/four_channel_placement.json` places four immutable R0 copies of the
frozen macro as adjacent 19.32 um columns. The array is 77.28 um by 184.21 um,
and the four `element_input` axes land exactly on `ua[0]` through `ua[3]`.
The generated placement GDS has SHA-256
`16908591b0896d5bc9dbe0eed99eec564c5f538a650e8e85d4a6db04078c8f33`.

The exact-abutment pilot passes the pinned Tiny Tapeout FEOL, BEOL, off-grid,
zero-area, pin-purpose, project-flat, and Magic DRC checks. Flat extraction
finds 1,292 devices: four equal 314-device non-dummy channel populations plus
36 grounded edge dummies. Every analog, phase, output, bias, power, and control
interface remains in four independent channel namespaces; only the intended
substrate/ground node is shared before top-level routing. See
`evidence/four_channel_placement_gate.json` and
`evidence/four_channel_placement_review.png`.

The placement GDS contains no new shared conductors. The next routing gate is
the differential output collector; it is reserved first because its symmetry
and loading directly set beam-sum gain and phase balance.

The first output-collector trial intentionally demonstrated why geometry-only
DRC is insufficient: an N tree promoted through M4 passed DRC but crossed the
selector phase network and reached 352 device terminals. That candidate was
rejected. The closed collector keeps both polarities in a verified empty M3
corridor, on separate vertical levels. Magic now finds exactly 120 intended
mixer-output terminals on each of `combined_p_internal` and
`combined_n_internal`, with all other interfaces isolated. The N tree is 2.0
um longer because of the vertically separated differential bands; the final
root-to-load/pad route must add 2.0 um to P and prove electrical equality with
distributed RC. See `evidence/four_channel_output_collection_gate.json` and
`evidence/four_channel_output_collection_review.png`.

The four shared phase inputs are now joined by four balanced H-trees above the
channel tops. Each phase uses a non-crossing M3 staircase and an M4 H-tree.
The staircase pitch is 1.0 um so via-3 landings retain 0.49 um clearance. The
tree heights compensate the original 0.8 um phase-port pitch, giving exactly
37.97 um from every one of the sixteen channel phase ports to its shared root.
Direct shuttle geometry, Magic DRC, and flat extraction pass; each shared
phase reaches exactly 32 selector terminals while the two output collectors
remain at 120 terminals each. See
`evidence/four_channel_phase_distribution_gate.json` and
`evidence/four_channel_phase_distribution_review.png`.

The two shared analog support trees now cross the congested selector-access
band only through eight isolated M4 elevators, then form separate balanced M3
H-trees in the verified-clear 157.51--162.17 um corridor. Flat extraction
merges all four channels into exactly one REF node with 64 original channel
terminal hits and one VBIAS node with 60 original channel terminal hits; no
other channel interface is merged. See
`evidence/four_channel_bias_reference_distribution_gate.json`.

The exact VCM divider/three-MIM block is placed west of the channel array, and
the full tail resistor/diode/two-MIM block is placed east. Their common M3
routes stay outside the frozen channel bodies. The first inherited tail-cap
route was rejected because it crossed the MIM bottom-plate Via-3 strip and
shorted VBIAS to ground despite zero DRC markers. The active generator instead
uses an M4 spine above the complete capacitor bboxes and separate drops to the
two C1 terminals. Integrated extraction now reports 1,312 devices, one 69-hit
REF net, one 79-hit VBIAS net, five correctly polarized MIM capacitors, zero
Magic DRC markers, and zero direct-GDS precheck markers. See
`evidence/four_channel_shared_support_integration_gate.json`.

The output stage adds two exact high-poly load resistors tied to the future
shared VDPWR rail and routes the differential sum directly to `ua[4]` and
`ua[5]`. The initially legal geometry had 12.61% extracted output-capacitance
mismatch, so it was rejected. The frozen replacement uses a compact 4.20 um
P-side MIM as deliberate compensation while keeping both signal routes direct;
it does not use a delay meander. Pad-to-mixer distributed extraction reports
0.3334% mean route-resistance mismatch, 0.1852% effective capacitance mismatch,
and 0.1652% estimated time-constant mismatch. Magic DRC and every pinned
direct-GDS shuttle precheck remain at zero markers. See
`evidence/four_channel_output_load_integration_gate.json`,
`evidence/four_channel_output_load_rc.json`, and
`frozen/four_channel_output_load_integration/README.md`.

The shared-power stage joins the four channel `VPWR` ports, the VCM divider,
the tail-bias block, and both output loads to one external `VDPWR` rail. It
also joins the channel guards/substrates and support grounds to one `VGND`
rail. A first candidate passed geometry DRC but shorted these rails where two
orthogonal Metal-4 trunks crossed. It was rejected by flat extraction. The
frozen replacement moves the west supply crossing to Metal 3 and extracts as
exactly two separate rails: 740 `VDPWR` and 1,360 `VGND` terminal occurrences,
with no residual hierarchical supply nodes. Magic DRC and every pinned
direct-GDS precheck report zero markers. A generator-level regression now
rejects any same-layer overlap between new supply and ground routes, pin
shapes, or via landings. See
`evidence/four_channel_power_integration_gate.json` and
`frozen/four_channel_power_integration/README.md`.

The centralized controller is now powered and physically joined to the analog
array. Its four phase outputs, 32 group-code bits, four channel-bias enables,
and one four-way mixer-blanking tree form 41 distinct routed nets with 85
endpoint attachments. OpenROAD finishes with zero violations; an independent
route-graph audit finds no missed endpoints, floating leaves, or loops. Direct
GDS checks and Magic DRC are zero. Flat extraction retains all 6,037 source
devices, keeps all 305 controller nets and both supplies distinct, and proves
that every phase reaches 32 selector terminals across all four channels. See
`evidence/physical_control_analog_handoff_gate.json` and
`frozen/controller_analog_handoffs/README.md`.

The 14 digital inputs now reach the exact official TinyTapeout terminal
rectangles through independently graph-audited M2--M4 routes. Exact-GDS
extraction proves 14 distinct boundary nets, one intended controller route per
input, no connection to either supply or an internal analog handoff, and no
change to the 6,037-device source population. All pinned direct-GDS checks and
Magic DRC remain at zero. See
`evidence/physical_control_boundary_handoff_gate.json` and
`frozen/controller_boundary_handoffs/README.md`.

The four analog inputs now use identical, straight, two-via escapes from the
exact `ua[0:3]` Metal-4 rectangles to their four channel input rails. Magic
extracts four independent nets, each reaching exactly fifteen gm gates and one
input-bias resistor, with no supply or previous-route short. Distributed metal
RC gives identical resistance vectors and 1.889 percent external-capacitance
span. At the intended 5 MHz input and a bounded 1 kohm source, the estimated
channel spread is 0.00000087 dB and 0.00249 degrees. Magic DRC and all pinned
direct-GDS checks remain at zero. See
`evidence/analog_input_escape_gate.json` and
`frozen/analog_input_escapes/README.md`.

The logical wrapper's constant-zero digital outputs are now implemented in
the physical GDS. All 24 `uo_out`, `uio_out`, and `uio_oe` terminals use one
straight Metal-4 bus to `VGND`, with no vias and 2.46 um clearance before the
nearest input pin. Exact extraction proves all 24 outputs are grounded,
`VDPWR` remains separate, and all 309 established signal groups are unchanged.
See `evidence/digital_output_tie_gate.json` and
`frozen/digital_output_tie/README.md`.

The authoritative current GDS is
`frozen/submission/tt_um_jjassonn69_beamformer.gds`, SHA-256
`824e38f94ce4fbff84d0c079dcb059d6944bca7569a0f657134c318f31553c14`.
The frozen electrical source remains immutable; the deterministic packager
adds only the official boundary/pin records and removes two redundant internal
power text labels. `evidence/submission_gate.json` is the consolidated signoff
authority. `frozen/submission/github_attestation.json` binds the green official
TinyTapeout workflow to this exact GDS hash. The remaining release step is
human visual review followed by fabrication submission without a geometry
change.

The complete operator-facing V3 datasheet is `docs/datasheet.md`. The bounded
power-on matrix passes all eight factorized cases: worst VCM 90% time is 19.235
us, worst VCM 2% settling is 49.011 us, and the required post-supply wait is 60
us. See `evidence/four_channel_startup.json`.

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

The first mismatch screen rejected the minimum-area 0.42/0.30 um gm and
2.5333/0.50 um tail devices. V3 now uses 0.84/0.60 um gm devices and
5.0667/1.00 um tail devices with a 64/1.00 um shared reference. Doubling both
dimensions preserves W/L while providing four times the matching area.

The promoted geometry passes the bounded five-corner vector sweep, 50 mV
compression, two-tone, all 56 ordered blanked transitions, and all-eight-state
filtered-spur gates. The blanked analog path settles in no more than 2 us under
its defined one-cycle measurement window. Across all eight phase states, the
unfiltered square-wave-mixer image is approximately -9.74 dBc and the defined
two-pole 2 MHz receiver response reduces the worst deterministic signal spur to
approximately -34.35 dBc.

The primary mismatch gate calibrates one codebook independently for each of
16 device-mismatch realizations using a 20 mV-peak tone, freezes that codebook,
and validates the same die with separate 5 mV-peak decks. The actual Gaussian
device factors are frozen and hashed so Apple ARM and Ubuntu x86 build
byte-identical inputs. The older disjoint-population global-codebook run is
retained as a non-gating stress diagnostic because one universal codebook is
not the intended calibration architecture. The 16-die campaign passes with
4.356 degrees worst validated phase error, 0.408 dB worst validated gain
ripple, and 1.574 V minimum output common mode.

Dimension-only PCell measurements identify a 3x5 active common-centroid matrix
with device-row edge dummies and one shared guard as the preferred candidate.
Its conservative estimate is 15.74 um wide on the 19.32 um input pitch,
leaving 3.58 um horizontal margin. This is not a placement or routing claim.

Run the additional pre-layout gates with:

```sh
python3 v3/tools/run_transition_settling.py
python3 v3/tools/run_spur_noise_characterization.py
python3 v3/tools/run_per_die_calibration_validation.py
python3 v3/tools/run_pcell_dimension_study.py
```

Run `run_mismatch_calibration_split.py` separately only to reproduce the
non-gating global-codebook diagnostic.

The periodic-noise gate uses a fully open-source, cross-checked equivalent
because ordinary ngspice `.noise` only linearizes a held switch state and its
PSS implementation does not support this driven mixer. VACASK 0.3.4.rc1 was
first qualified against analytic noise and then against ngspice using the
exact V3 SKY130 device geometries. It simulated the complete 15-slice channel
with driven 4 MHz quadrature switching for four deterministic seeds in each
of all eight required states. The 100 us post-settle records measure 41.62 uV
RMS mean output noise from 10 kHz to 2 MHz, with a 2.154 dB span between state
means. Reduced-amplitude noise injection was required to avoid compact-model
timestep collapse; a separate three-scale gate passes with R-squared
0.99999496 and 0.080 dB extrapolated spread.

An independent 32-snapshot ngspice/Fourier calculation predicts 34.98 uV RMS
over the same band and 35.10 uV RMS from 10 Hz to 2 MHz. Its +1.51 dB
agreement with the switched transient result passes the declared +/-3 dB
limit. Combining the noisiest driven state mean with the independently folded
10 Hz--10 kHz increment gives a conservative 48.01 uV RMS estimate and 38.6 dB
minimum nominal output SNR for the 5 mV-peak input case. See the
[periodic-noise summary](evidence/periodic_noise_summary.svg).

This closes the V3 pre-layout electrical gate and authorizes floorplanning.
It is not native PNoise and excludes clock-source phase noise, extracted
layout parasitics, package/board noise, and silicon correlation. V3 is still
not a GDS, submission, or fabrication candidate.

## Constraint-only floorplan checkpoint

The first reproducible V3 floorplan is now captured in
`layout/floorplan.json`. It keeps the four 15.74 um channel envelopes directly
above the official analog pins, preserves a 3.58 um gap between adjacent
shared guards, repeats the exact 3x5 common-centroid group assignment in every
channel, reserves one local selector region per channel, and uses a balanced
four-phase distribution tree. The two output-pin paths are each 172.75 um and
have identical Metal 3 and Metal 4 length budgets; all eight local channel-to-
sum-bus taps are 6.01 um.

The manifest is generated rather than hand-edited. Rebuild and check it with:

```sh
python3 v3/tools/build_floorplan.py
python3 v3/tools/check_floorplan.py --report v3/evidence/floorplan_check.json
python3 v3/tools/render_floorplan.py
python3 -m unittest v3.tests.test_floorplan -v
```

The review image is `evidence/floorplan_review.svg`. This checkpoint does not
instantiate devices or routes and does not authorize GDS.

Physical Gate 3B measured four guarded foldings of the shared 64 um / 1.00 um
tail reference in pinned Magic 8.3.676. The selected 8-by-8 um folding is
11.99 by 10.10 um (121.10 um2), smaller and much squarer than the 4-by-16,
16-by-4, and 32-by-2 alternatives. Its reserved location is now shown in the
floorplan. The completed physical pilot proves all eight 8/1 um fingers are
diode-connected with D/G=`vbias_ref` and S/B=`VGND`, clears Magic DRC and all
applicable direct-GDS Tiny Tapeout geometry decks, and contains no orphan via
or route stub. Endpoint-rooted distributed extraction reports 22.3824 ohm of
common upstream resistance and four identical 9.1564 ohm post-star branches
(0.0 percent mismatch against a 1.0 percent limit). See
`evidence/tail_reference_physical_gate.json`. This closes the isolated
reference/tree pilot; VCM, decoupling, loads, channel devices, and integrated
top-level requalification remain open.

Each channel's 34 um-high selector reservation now also has an explicit
nine-row standard-cell skeleton. It uses twelve 2:1 muxes, four AND gates,
five inverted-input AND gates, five taps, and seventeen one-site filler cells
per channel. Exact tracked LEF dimensions give 42.08 percent raw utilization;
the widest row is 10.12 um in a 15.74 um channel. The actual named cell/pin
graph passes exhaustive Boolean checking for all phase inputs, codes, enable
states, and blanking states.
See `evidence/selector_placement_review.svg` for an enlarged row-by-row view.

Physical Gate 3C routes one complete selector against the real SKY130 HD LEF
pin geometry. Abutted functional cells produced repeatable LI pin-access
spacing errors, so the authoritative generator now inserts one 0.46 um filler
site at every signal-cell boundary. An attempted 0.68 um vertical row channel
was rejected even after it routed: the same FEOL deck used by Tiny Tapeout
reported 33 `MR_nwell.SP.1` markers. Contiguous alternating R0/MX rows with
the horizontal fillers pass with 0 OpenROAD violations, 0 Magic DRC/import/
extraction/GDS-writer errors, all 208 expected transistors and 22 boundary
nets present after flat extraction, and 0 markers in the pinned Tiny Tapeout
FEOL, BEOL, off-grid, zero-area, and pin-purpose-overlap decks. See
`evidence/selector_route_pilot.json`.

This is a pilot-geometry result, not an official submission precheck. The
complete wrapper, project boundary, LEF/Verilog contract, power pins, analog
pins, antenna repair, four-channel route balance, and integrated GDS remain
mandatory later gates.

With a pinned `tt-support-tools` checkout and KLayout available, repeat the
pilot geometry subset with:

```sh
python3 v3/tools/run_selector_precheck.py \
  --support-tools /path/to/tt-support-tools-at-d65690e
python3 v3/tools/check_selector_route_evidence.py
python3 -m unittest v3.tests.test_floorplan -v
```

The runner refuses a support-tools checkout at any other commit. It reads the
KLayout report databases and fails on nonzero markers even when the underlying
deck process itself exits successfully.

## Current integrated controller checkpoint

The centralized four-channel controller is now physically placed and all 305
of its internal signal nets are routed against the exact frozen analog and
shared-power GDS.  The implementation contains 291 functional cells, 208 well
taps, and 1507 fillers in 17 contiguous alternating rows.  Signal routing is
limited to LI through Metal 3, leaving Metal 4 available for controller power
and later top-level handoffs.

The first controller-only route looked clean to OpenROAD but was correctly
rejected by full-chip extraction: 21 nominally separate nets touched a frozen
vertical Metal 3 ground spine that the controller-only DEF did not describe.
The input generator now derives routing obstructions from the hash-locked
frozen GDS itself.  The corrected route crosses that spine on Metal 2 and has
zero extracted contacts to it.

Before power integration, a clean but edge-fed power candidate was rejected
for excessive M1 rail length.  The authoritative signal router now reserves
two distributed M2/M3 power contacts on every row boundary before routing.
The resulting signal route remains zero-violation and limits nominal M1
distance to a power contact to 34.68 um.  Reserving all 36 contacts and nine
ground-underpass corridors adds only 106.075 um (0.94 percent) of signal
centerline compared with the first clean route.

The frozen corrected signal checkpoint passes zero OpenROAD detailed-route
violations, zero Magic DRC markers, and zero applicable direct-GDS Tiny
Tapeout geometry markers.  More importantly, the complete flat extraction
contains the exact 6037 expected devices and retains all 305 route labels as
305 distinct electrical groups, each incident on at least two device lines.

Controller power is now closed as a separate physical gate.  All 18 M1 row
boundary rails have two redundant M1-to-M4 contacts at x=215.66 um and
x=285.02 um.  VDPWR uses a right-side M4 collector; VGND uses a split
left-side collector and nine M3 underpasses beneath the frozen vertical VDPWR
M4 spine.  The final 0.60 um M4 row fingers pass the flattened spacing deck;
the earlier 0.80 um trial was rejected because one finger came within 0.28 um
of an inherited VGND trunk.

Full extraction of the powered checkpoint produces only the two intended
overlay nodes, VDPWR and VGND.  Both are single connected components, they
remain mutually distinct, no power via is orphaned, and none of the 305
controller nets is shorted to a supply.  Magic DRC and every applicable pinned
Tiny Tapeout/KLayout subset remain at zero markers.  This closes controller
signal and power integration; it does not yet close external handoffs, antenna
repair, post-layout timing/RC, or the packaged Tiny Tapeout submission checks.

See `evidence/physical_control_signal_routing_gate.json`,
`evidence/physical_control_power_gate.json`, and the immutable artifacts in
`frozen/controller_signal_routing/` and `frozen/controller_power/`.
