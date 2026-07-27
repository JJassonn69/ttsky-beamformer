# V3 manual-routing canvas

File: `beamformer_v3_manual_routing_canvas.gds`  
Top cell: `v3_channel_architecture_feasibility`  
Scope: one 15-vector-unit channel, not the final four-channel top level.

The canvas already contains the placed transistor PCells, device-local wiring,
local LON/LOP merges, the common-centroid orientation pattern, and the shared
substrate guard/ground connection. Do not move, rotate, delete, or redraw those
objects. Add only the inter-unit/global routes described below, and save the
result under a new filename.

## What connects to what

For every unit `u00` through `u14`:

- `uXX_sig` -> shared channel net `sig`
- `uXX_ref` -> shared channel net `ref`
- `uXX_vbias` -> shared channel net `vbias`
- `uXX_outp` -> shared differential sum net `row_outp`
- `uXX_outn` -> shared differential sum net `row_outn`
- `uXX_lop` -> the `gN_lop` net shown in the group table below
- `uXX_lon` -> the matching `gN_lon` net shown in the group table below
- `VGND` is already joined through the row ground buses and shared guard. Do
  not connect any signal, phase, output, `ref`, or `vbias` route to `VGND`.

Never join `lop` to `lon`, `outp` to `outn`, `sig` to `ref`, or one binary
group's phase net to another group's phase net.

## Unit-to-phase-group table

| Unit | Matrix position | Weight group | LOP destination | LON destination |
|---|---|---:|---|---|
| `u00` | top-left | 8 | `g8_lop` | `g8_lon` |
| `u01` | top-centre | 8 | `g8_lop` | `g8_lon` |
| `u02` | top-right | 8 | `g8_lop` | `g8_lon` |
| `u03` | upper-left | 4 | `g4_lop` | `g4_lon` |
| `u04` | upper-centre | 8 | `g8_lop` | `g8_lon` |
| `u05` | upper-right | 4 | `g4_lop` | `g4_lon` |
| `u06` | centre-left | 2 | `g2_lop` | `g2_lon` |
| `u07` | centre | 1 | `g1_lop` | `g1_lon` |
| `u08` | centre-right | 2 | `g2_lop` | `g2_lon` |
| `u09` | lower-left | 4 | `g4_lop` | `g4_lon` |
| `u10` | lower-centre | 8 | `g8_lop` | `g8_lon` |
| `u11` | lower-right | 4 | `g4_lop` | `g4_lon` |
| `u12` | bottom-left | 8 | `g8_lop` | `g8_lon` |
| `u13` | bottom-centre | 8 | `g8_lop` | `g8_lon` |
| `u14` | bottom-right | 8 | `g8_lop` | `g8_lon` |

The required final phase ports are therefore exactly:
`g1_lop`, `g1_lon`, `g2_lop`, `g2_lon`, `g4_lop`, `g4_lon`, `g8_lop`, and
`g8_lon`.

## Existing port layers

- `uXX_sig`, `uXX_ref`, `uXX_vbias`: Metal 4
- `uXX_outp`, `uXX_outn`: Metal 3
- `uXX_lop`: Metal 4 local-merge root
- `uXX_lon`: Metal 3 local-merge root
- `VGND`: Metal 3/shared guard

## Recommended layer ownership

- Use Metal 2 for long vertical `row_outp`, `row_outn`, `sig`, `vbias`, and
  `ref` service spines in the two gaps between the three unit columns.
- Use short Metal 3 row buses to join unit outputs/analog branches to those
  Metal 2 spines.
- Use Metal 4 primarily for long phase distribution and short phase handoffs.
- Keep phase crossings separated by layer. In mixed G8/G4 rows, do not run a
  centre-G8 horizontal bus through the right G4 unit's phase escape on the
  same layer.
- Make every via intentional: it must have legal same-net metal on both sides
  and must continue to a component, branch, or port. No via-only islands or
  floating landing pads.

Use at least 0.40 um for normal M3/M4 signal routes, 0.60 um for the two output
row buses, and at least 0.30 um same-layer spacing. Keep `row_outp` and
`row_outn` geometrically symmetric; do the same for each `gN_lop/gN_lon` pair.
Avoid artificial meanders and do not route through transistor PCells merely
because another metal layer makes the crossing electrically possible.

Before handing the edited file back, save it as a new GDS and report which
layers you changed. The automated flow will transfer the geometry into a
reproducible generator, run Magic DRC/extraction, verify the named topology,
run the pinned Tiny Tapeout FEOL/BEOL/off-grid/zero-area decks, and check for
dead-end vias and floating metal.
