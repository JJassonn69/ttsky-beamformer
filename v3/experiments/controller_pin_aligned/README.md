# V3 controller Candidate B: pin-aligned north interface

This experiment preserves the signed-off V3 submission as immutable Candidate
A.  Candidate B changes only the placement of controller ingress cells and the
ordering/spacing of the controller's fourteen north boundary ports.  The
controller logic, analog hierarchy, channel placement, tail-bias support,
output network, and official Tiny Tapeout pin rectangles remain unchanged.

The experiment addresses one specific physical-design weakness in Candidate
A: its local controller ports are spread across the north edge in semantic
order, while the official Tiny Tapeout pins use a different left-to-right
order.  The boundary router therefore has to reorder those nets in the narrow
top corridor.  Candidate B instead:

- orders local ports exactly like the fixed Tiny Tapeout pins;
- uses a six-Metal-2-track (2.76 um) pitch so the port bank is compact;
- places configuration-clock/latch fanout buffers in the northwest ingress
  row and main clock/reset fanout buffers in the northeast ingress row;
- preserves the west-facing phase and channel-control output drivers;
- keeps the exact Candidate A controller rectangle, power-contact
  reservations, and analog obstruction map.

No Candidate B result may replace Candidate A unless it improves the routed
boundary geometry and passes placement, detailed-route, direct-GDS, Magic DRC,
and extraction-topology gates.  The immutable Candidate A hashes are recorded
in `candidate_a_manifest.json`.

Result: Candidate B closes every experiment gate while keeping all analog
support placement fixed. Compared with Candidate A, it reduces both controller
wire/vias and the Tiny Tapeout top-interface wire/vias. The full hash-bound
comparison is generated at
`build/v3/experiments/controller_pin_aligned/candidate_comparison.json`.

The broader vertical-controller/support-relocation proposal is therefore
deferred. Moving capacitors for visual grouping is not justified when the
controller-only change already solves the top-interface problem without
disturbing analog return-current paths.
