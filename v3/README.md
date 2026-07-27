# Beamformer V3 workspace

## Current physical-design input

The only approved V3 channel macro is
`frozen/one_channel_macro/v3_channel_selector_late_promotion.gds`, with
SHA-256 `4cd2d39ba041ac80391516b35140ce79e476117fd4e73ae22795c565befbd274`.
`CURRENT.json` is the machine-readable authority. Run
`python3 v3/tools/assert_current_channel.py` before using a channel GDS in the
four-channel floorplan. Pilot, manual-canvas, and pre-late-promotion GDS files
are historical and must not be used as physical inputs.

The next physical stage places four immutable copies of this macro and routes
their shared phase, bias, power, control, input, and output infrastructure.

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
