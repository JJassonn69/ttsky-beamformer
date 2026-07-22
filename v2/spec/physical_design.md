# V2 production physical-design plan

Status: production placement, power, and control-routing checkpoint.  The
analog channel, local phase selector, shared support network, mapped 194-cell
control core, fixed helper cells, and exact assembled power grid pass the
pinned Magic full DRC with zero violations. One OpenROAD job owns all 206
physical digital-control nets; compact deterministic overlays add the 16 trim,
12 phase, and four quadrature analog handoffs. Final extraction verifies all
206 route labels, 790 terminal attachments, all 968 mapped/helper power and
body pins, and the four analog resistor terminal triplets. Post-layout analog
and phase-code simulation, independent foundry-qualified LVS where available,
and the official TinyTapeout workflow remain pending; this checkpoint is not
yet a fabrication release.

The V2 layout must be derived from the real TinyTapeout 2x2 pin geometry, not
from a visually symmetric empty rectangle. The authenticated template is
334.88 by 225.76 um, but the six usable analog pins remain along the lower edge
of the left half. Consequently, distributing four analog channels across all
four geometric quadrants would waste wire and worsen matching.

The machine-readable source of truth is
[`v2/layout/floorplan.json`](../layout/floorplan.json).

## Selected macro organization

1. Put four narrow, identical channel slices directly above `ua[0:3]`. Their
   centers inherit the exact 19.32 um pin pitch, so each external input rises
   monotonically into its own slice with no lateral jog or U-turn.
2. Keep each transconductor, tail device, local mixer, and phase selector
   inside its channel slice. High-impedance GM nodes must not cross between
   slices.
3. Center the shared differential summing structure on the four channel
   positions rather than on the full 2x2 die.
4. Offset the matched P and N load locations by the same 19.32 um as their
   output pins. Route equal M3 vertical totals and equal M4 horizontal totals
   through explicit named bends. The horizontal tracks are separate and any
   geometric P/N crossing occurs on different layers, never by overlap.
5. Put the quadrature generator near the upper digital pins and root its
   four-wire phase bus at the arithmetic mean of the channel centers.
6. Use a two-level H-tree. Both root-to-pair branches and pair-to-channel
   leaves are naturally equal. No meander is permitted for clock matching.
7. Keep the switched-tail trim bank inside each channel.  Only static digital
   enables enter it; no analog trim voltage crosses a channel boundary.
8. Reserve the added right-hand area for quiet decoupling, configuration logic,
   and future verified support circuitry.  Empty space remains electrically
   quiet unless extraction proves a grounded shield beneficial.

## Digital-control placement and power checkpoint

The control logic is not row-packed in synthesis order.  Forty-nine phase-bank
cells follow channel and shift-chain data flow, 64 trim-bank cells use one
active pair and one shift pair per row, and 81 global cells place the
quadrature generator, synchronizers, active state, and configuration logic
beside their physical consumers.  Connectivity relaxation legalizes only the
36 residual global cells.

Every cell origin is on the 0.46 um SKY130 HD site grid and every row follows
the R0/MX power-abutment convention.  A second deterministic orientation pass
tests the legal R0/MY or MX/R180 alternatives for the 36 residual cells using
actual LEF pin coordinates.  It mirrors 19 cells, reduces their pin-to-neighbor
demand by 50.109 um (3.91%), and raises total weighted-HPWL improvement over a
naive row-major placement to 29.77%.  Structured storage chains and matched
decode cells are excluded from that optimization so a small numerical gain
cannot destroy their intentional topology.

The final placement contains 194 mapped cells, 269 explicit well taps, and
4,750 one-site `sky130_fd_sc_hd__fill_1` cells.  The fillers are not decorative
metal.  They are immutable foundry-library macros used only to close every
complete row site and preserve well, implant, LI, and rail continuity.  An
earlier extraction without them found eight floating VPB islands even though
M1 power rails visually crossed every cell.  With the fillers, extraction
recovers all 194 cells and verifies 776/776 VPWR, VPB, VGND, and VNB terminals
on the correct named supply.

Power uses 35 alternating M1 row rails, two independent upper contacts per
rail, redundant M3 edge straps, and short M4 distribution trunks.  The
generated overlay contains 490 shapes, 70 upper contacts, 102 via1 cuts,
102 via2 cuts, and 49 via3 cuts.  Each of VDPWR and VGND is one connected
component; there is no project metal5, cross-net spacing violation, signal
keepout intrusion, or unowned via.

The exact placement GDS is assembled without rewriting foundry macro polygons.
During development, a GDS SREF encoded `ANGLE` without the required preceding
`STRANS`; Magic printed an import error but still returned zero DRC and zero
feedback.  The assembler now emits a zero-valued `STRANS` for R180, and every
Magic-log gate treats `Unexpected record type` and `Error while reading cell`
as fatal.  A zero DRC count alone is therefore no longer accepted as evidence.

Frozen powered checkpoint:

- top: `v2_four_channel_control_powered`;
- GDS SHA-256:
  `cf25e276fcb99a6c5e8559822ded5b4ec132e616a9a9583bbce3d425db7b6f81`;
- direct-GDS Magic full DRC: 0;
- Magic import feedback: 0;
- extracted mapped supply/body connections: 776/776; and
- analog VDPWR endpoints: `RBIAS.R1`, `RVCM_TOP.R1`, `LOAD_N.R1`, and
  `LOAD_P.R1`, all with distinct bodies on VGND and R2 terminals on their
  intended bias, common-mode, or differential-output nets.

A pre-freeze candidate placed the phase-selector VGND trunk across the R1
terminals of both output-load resistors.  That geometry was DRC-clean but
electrically collapsed each three-terminal load into a body-grounded
two-terminal extraction.  The release gate now checks B, R1, and R2 separately
for all four analog resistors, reserves the complete load-device keepouts
against VGND, and includes a negative regression that recreates the rejected
grounded-load failure.  This is why a clean DRC count is never treated as a
connectivity signoff.

## Control-route allocation

[`v2/layout/control_signal_plan.json`](../layout/control_signal_plan.json) is
the route-allocation contract.  It accounts for all 207 mapped signal nets,
719 mapped pin endpoints, and 45 real external or analog handoff anchors before any
signal rectangle is generated. The assigned classes are 111 local-direct,
39 regional-trunk, 16 trim-handoff, 12 phase-handoff, nine direct-boundary,
nine external-input, six service-tree, four quadrature-handoff, and one
observation-only net. `mixers_blank` is deliberately not routed: blanking is
already folded into all four `phase_enable` outputs, and extraction proved the
former `(123.28,176.0)` target was only an unconsumed label rather than an
analog load or real macro pin. This prevents a 36.19 um floating test stub.

Before signal routing, `build_control_pin_access_catalog.py` transforms every
LEF port rectangle through the cell placement orientation and emits legal
contact candidates. For LI pins, the complete 0.17 um contact landing must
remain inside the named LEF port. A route may not use a visually convenient
point outside that inset region: exact extraction showed that such an escape
can silently connect an internal cell node even when Magic reports zero DRC
errors.

Interval coloring measures—not assumes—upper-metal capacity. Required M4
track counts are 11 of 22 in the phase bank, 25 of 38 in the global core, and
21 of 62 in the trim bank, leaving margins of 11, 13, and 41 tracks. Dense pin
pairs are explicitly counted and
must receive short staggered M2 escapes before private M3 leaves; they may not
be hidden by overlapping landings or long return routes.

The first generated signal block contains the 16 active trim controls.  Each
route connects the mapped active-state Q pin to its feedback mux A0, descends
on a unique M3 column, crosses to one unique M2 bus row, and rises once at the
actual channel-local inverter input. The manual overlay has at least 1.625 um
M3 column pitch, 0.64 um M2 bus pitch, no M4/M5, no U-turn, and two legal
0.20 um via2 cuts per net; the router-owned access to the source pins is reused
instead of duplicated. The exact assembled trim GDS has SHA-256
`3b8e7f752813a71b1e31db1d25e7bb123200088299292241779aea2bc452cc96`
and passes full-chip Magic DRC with zero feedback.  Extraction verifies 48/48
required endpoint roles: one active-state Q, one feedback-mux A0, and one
channel-local inverter A per named trim net.  An earlier boundary-only version
also had zero DRC, but extraction correctly rejected all 16 missing inverter
connections; this negative result is retained in the design rationale.

## Final control-routing checkpoint

The production route is deliberately single-owner. One unified OpenROAD job
sees all 206 physical control nets and all 763 router endpoints at once,
including the nine direct-boundary and six high-fanout service-tree classes.
This replaced the earlier sequential direct/service overlays that could make a
later route depend on a stale obstacle map. The audited route has 7,552.55 um
of wire, 1,466 vias, no cycle, no unattached leaf, and no signal above M4.
Only 13 nets use M4. The worst route/HPWL ratio is 1.815 on `rst_n`, and the
worst two-pin ratio is 1.592; no artificial delay or clock/reset meander is
present.

The 16 trim, 12 phase, and four quadrature handoffs are short deterministic
extensions from named router pins to real analog cell terminals. They reuse an
existing OpenROAD transition where that is the shortest legal connection.
Every new via2/via3 cut is exactly 0.20 by 0.20 um with explicit lower- and
upper-metal enclosure. Same-net bridge patches are added only where needed to
close a real landing notch. The quadrature extension requires only two new
via2 cuts for four roots because the other two roots already have a suitable
router transition.

The frozen local candidate is
`build/v2/control_routing/direct/v2_control_quadrature_routed.gds`, top
`v2_control_quadrature_routed`, SHA-256
`d9c9aae5771af815833668374924baee23f60a51747c7966e2517dcb6f6a6130`.
Its acceptance evidence is:

- pinned Magic full-chip DRC, GDS-import feedback, and extraction feedback: 0;
- exact topology extraction: 206/206 route labels, 790 verified final
  endpoints, 48/48 trim roles, 12/12 phase nets, and 4/4 quadrature roots;
- 194 mapped standard cells, 48 fixed helper cells, and 968/968 power/body
  pins preserved, with no signal-to-power short;
- terminal-aware checks keep `B→VGND`, `R1→VDPWR`, and the intended R2 net on
  RBIAS, RVCM_TOP, LOAD_N, and LOAD_P;
- direct-GDS flat checks find no via-only M3 island, via enclosure error,
  MIM-clearance error, stale transition, or malformed contact cut;
- KLayout open_pdks full-deck delta: 2,776 normalized inherited markers in
  both the routed source and final hierarchy, with zero added and zero removed;
  and
- full distributed-RC extraction: 91,671 explicit resistors, 34,316
  capacitors, 4,244 devices, and coverage for all 254 required control, analog,
  output, bias, and supply nets.

Magic canonicalizes the VGND resistor graph under the flattened standard-cell
bulk node `sky130_fd_sc_hd__fill_1_2190.VNB`.  The RC gate does not waive the
name mismatch: it parses the ordinary extraction equivalence records, proves a
direct path from `v2_control_power_overlay_0.VGND` to that emitted resistor
graph, and fails if either the equivalence or the graph is absent. The emitted
SPICE contains 94.47% as many explicit resistor elements as the annotated
`.res.ext` network after equivalent-node reduction; the gate requires at least
90%, positive well-formed elements, preserved device count, and complete
252-net coverage.

Magic emits one `viali ... smaller than extract section allows` message during
`extresist`. Upstream Magic source shows that this branch falls back to one RC
contact node when a contact is smaller than the CIF contact-array meshing
section. It is classified, not ignored: the final GDS independently proves all
21,504 mcon cuts are exactly 0.17 by 0.17 um, Magic physical DRC is zero, and
the KLayout marker multiset is unchanged. Any additional or unclassified Magic
warning fails the final RC gate.

The KLayout number is deliberately reported as a delta, not as a false
zero-marker claim.  The generic open_pdks deck reports inherited foundry
library/PCell markers in the clean source hierarchy as well.  The final route
must preserve that normalized marker multiset exactly, while pinned Magic is
the foundry-aware physical-rule authority for this checkpoint.  The official
TinyTapeout workflow and an independent foundry-qualified signoff remain
mandatory before fabrication.

## Orientation study

Rotation or mirroring is an optimization variable, not an aesthetic choice.

- `R0` is the baseline for every channel and every unit resistor.
- A complete channel or mixer sub-block may be evaluated with `MY` if it puts
  its output-facing terminals toward the summing bus and measurably shortens
  local routing.
- `MX` and 90/180/270-degree rotations are forbidden until a generated PCell
  proves identical terminal mapping, body/well contacts, stress direction,
  DRC, LVS, and extracted parasitics.
- All tail-current units retain one absolute device orientation.  Forty-two
  fixed units are grouped 14/14/14; binary groups contain 1/2/4/8 copies of
  the same 1.26 by 0.50 um unit finger.
- The differential load pair uses identical orientation and contact style.

For every candidate orientation, the placement report must record total
weighted wire length, longest critical path, crossings, via sites, keepout
intersections, and extracted pair mismatch. The shortest legal candidate wins;
there is no manual preference for mirrored artwork.

The measured terminal study selected `R0` for every left-hand GM/mixer PCell
and `MY` for its right-hand partner. Relative to all-`R0`, this reduces local
source collection by 3.10 um per channel and changes the summed outer-drain
escape imbalance from 3.10 um to numerical zero. The choice remains
conditional on DRC, terminal-aware extraction, and post-layout equivalence.

The placement-stage DRC portion of that condition is now satisfied.  Magic's
`h` transform was verified to produce the intended MY matrix `(-1,0,0,1)`;
using its `v` transform would produce MX and is prohibited by the generator.

Within each channel the two signal/reference GM halves use an ABBA ordering;
their geometric centroids are exactly equal.  Every mixer row contains one
`gm_p` and one `gm_n` switch and one P-output and one N-output switch.  The
left/right ownership reverses after two rows, while the LO polarity follows a
vertical ABBA sequence.  This gives equal centroids for the GM branches, P/N
output devices, and LO-P/LO-N gate loads simultaneously; merely balancing the
latter two would leave a systematic high-impedance GM routing error. Three
14-finger fixed-tail rows and the 1/2/4/8 trim rows sit directly below the GM
pair inside one local substrate guard.

The initial placement put the complementary trim-control inverters in the
phase-selector region at `y=137 um`. A first local-route study moved them to
`y=85 um`, but the two intentional M4 mixer-output crossovers then obstructed
all eight vertical controls. The production placement instead uses the quiet
unused region at `y=24 um`, below the trim guard. This shortens the switch-to-
inverter routes by about 15 um, avoids every mixer/output crossing, and permits
one monotonic M4 column per static control without bridge vias. Current group,
switch pair, and inverter order are all `[bit 2, bit 3, bit 1, bit 0]` from
left to right. This non-numeric physical order follows the actual 4/8/2/1
device positions and removes static-control crossings by placement rather
than by extra metal.

The first-stage phase muxes use the opposite mirror assignment from the final
P/N muxes: `PMUX_A=MY` and `PMUX_B=R0`. This points both first-stage outputs
toward the channel center, where their two-load trees branch to the final
muxes. A measured-pin HPWL study reduces the aggregate internal-tree span by
more than 3 um per channel versus outward-facing outputs, with no added cell,
load, or device orientation. The final P/N muxes remain `R0/MY` so their
outputs face the left/right blanking gates and buffers.
Both mux rows and their well taps are also shifted left by `0.23 um` from the
initial placement. Their P/N centers, central row gap, and inward-facing
first-stage outputs are therefore exact mirrors about `x=0.92 um`, the same
axis used by the analog core. This eliminates a systematic half-site route
offset rather than hiding it with added metal.

## Routing hierarchy

The frozen local lane map is machine-readable in
[`v2/layout/routing_plan.json`](../layout/routing_plan.json). It reserves
straight M3 tracks for the input and its ground shield, mirrored LO branches,
mirrored P/N output collectors, mirrored GM-P/GM-N collectors, a centered
tail track, and separate bias/reference tracks. Every pair is geometrically
mirrored about `x=0.92 um`; overlapping same-layer tracks retain at least
`0.30 um` edge clearance. M2 is reserved for short terminal ladders, while M4
is reserved for intentional crossings and global trunks. This makes the route
topology reviewable before a single rectangle is painted. Each LO polarity
uses two monotonic vertical branches, one per loaded mixer row. This preserves
the original analog-common-centroid mixer order while giving LO-P and LO-N
exactly equal aggregate M3 length and via count; it does not use a serpentine
or a return path.

### Element inputs

The pin-to-slice entry is a straight 7.5 um vertical path. Transition away
from M4 near the boundary and use identical via stacks. Input bias pickup and
both halves of the local transconductor branch only inside the slice.

### Local analog current nodes

GM, tail, and mixer-source nodes use local interconnect and M1/M2 wherever
possible. They do not leave the channel slice. M3 is allowed only when a local
crossing cannot be removed by component orientation or ordering.

### Differential summing and output

Mixer outputs enter short, wide P and N collection structures. The two load
centers and output pins have equal planned Manhattan distance, equal layer
lengths, and equal via sites. Their horizontal tracks are parallel and
separate inside a named summing corridor above the channel devices; the long
vertical legs stay on the output-pin columns to the left of the channel array.
The N route uses one short local M3 offset so its total M3 length equals P.
Different channel tap distances are
handled through a symmetric central bus and verified electrically with
distributed RC; they are not equalized with serpentine routes.

Output routing starts at the measured resistor `R2` terminal at local
`y=-7.71 um`, not at the PCell bounding-box edge.  With load centers at
`y=107 um`, both electrical route anchors are therefore `y=99.29 um`.

### Phase distribution

Four phase wires travel together in a fixed order. M4 is preferred for
horizontal trunks and M3 for vertical leaves. A ground shield separates the
bundle from inputs, trim controls, and output loads. Every leaf has the same drawn
length and via count by topology. Extracted skew, not artwork length, is the
release metric.

Each local phase selector uses four pinned `sky130_fd_sc_hd__mux2_1` cells:
two shared first-stage muxes form phase pairs A/B, then matched P/N muxes select
A/B in opposite order. Matched `and2_1` cells provide channel blanking and
matched `buf_4` cells drive the mixer gates. Thus every P/N path contains the
same cell sequence and every global phase sees the same input loading.

A 30-case transistor-level sweep covering TT/FF/SS/FS/SF, three paired
voltage/temperature extremes, all four phase codes, and both 4 and 30 MHz
passed. Worst measured P/N rise and fall skew were 2.006 ps and 7.966 ps;
worst duty mismatch was 0.004%, and worst simultaneous-high overlap was 2.4%
of a period. These are schematic/interconnect-load results, not extracted
layout claims.

### Gain trim and R-2R trade study

The production trim is a local equal-unit current bank.  Its drain collection
is a short local tail node, its sources land on one local ground strap, and its
four gate groups are selected by static complementary digital controls.  The
controls must settle before the channel exits the one-LO-period blanking
interval.

The fabricated R-2R reference still informed the study: identical unit
elements, straight repeated connections, and uniform drivers are good layout
practice.  A V2 high-poly ladder using those rules passed a 54-case PVT/load
sweep.  It was not selected for V2A because the simplest passive interface
loaded the shared bias, while an active buffer increased risk and routing.
The research netlist remains reproducible but no R-2R devices may appear in
the V2A placement manifest.

## Placement acceptance gates applied

The generated placement is accepted only while all of the following pass:

- exact official 2x2 template hash and pin-coordinate check;
- four channel centers aligned to `ua[0:3]`;
- non-overlapping channel slices with equal pitch and equal dimensions;
- equal H-tree path length and named branch-only via locations;
- equal planned differential output distance;
- reserved passive, guard-ring, power, clock-shield, and boundary keepouts;
- component bounding boxes derived from generated PCells rather than guessed
  schematic dimensions; and
- orientation cost report selecting a legal minimum-route candidate.

## Detailed-routing acceptance gates

- No route may reverse direction unless an approved obstacle forces a single
  named dogleg; length-matching U-bends are prohibited.
- No via may exist without metal ownership above and below.
- No same-net floating landing, dead-end stub, or abandoned transition is
  permitted.
- No unrelated net may enter a resistor, MIM, guard-ring, or clock-shield
  keepout.
- Every regenerated route starts from the clean placed cell.
- The route checker compares endpoint connectivity, layer lengths, via counts,
  spacing, and keepouts before Magic is invoked.
- Magic DRC, topology extraction, independent LVS when available, direct-GDS
  flat checks, and full distributed-RC coverage remain mandatory.

Empty space is not filled merely to make the die look occupied. Only required
foundry density structures or shielding proven beneficial after extraction may
be added; decorative or floating metal is forbidden.
