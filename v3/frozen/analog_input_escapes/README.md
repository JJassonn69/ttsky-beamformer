# Frozen V3 analog-input escapes

This checkpoint adds the four `ua[0]` through `ua[3]` input connections to the
frozen controller-and-analog top. The only valid downstream source is
`v3_four_channel_analog_inputs.gds`, SHA-256
`5dae3f99aa6836eaf61a7224096781465965899118d2413040dee4f91dcdfa88`.

Each route is the same straight structure: the exact 0.90 by 1.00 um
TinyTapeout Metal-4 terminal, one Via-3, a 9.735 um Metal-3 trunk, one Via-2,
and a Metal-2 landing on its channel input. There are no bends, meanders,
direction reversals, or Metal-5 shapes. The four routes are exact horizontal
translations and use two vias each.

Exact-GDS Magic extraction retains all 6,037 source devices and finds four
distinct input nets. Each reaches exactly fifteen gm gates and the one input
bias resistor in its intended channel, with no connection to either supply or
any previous route label. Magic DRC and the pinned TinyTapeout FEOL, BEOL,
off-grid, zero-area, pin-purpose, and project-flat checks all report zero
markers.

The distributed metal-RC gate includes the conductor resistor network rather
than capacitance-only extraction. All four resistance vectors are identical:
pad-to-gm paths range from 255.09 to 286.08 ohm, with a 270.44 ohm mean. The
extracted external capacitance is 72.41--73.79 fF, a 1.889 percent span. With
a bounded 1 kohm source at 5 MHz, the estimated channel-to-channel spread is
0.00000087 dB and 0.00249 degrees. The 200 MHz diagnostic remains small at
0.00137 dB and 0.0986 degrees of channel spread, although its common phase
lag is 5.30 degrees and is not the V3 operating-frequency claim.

`01_integrated_input_escapes.png` shows the complete layout, `02` isolates the
four new routes, `03` shows the Metal-2 channel landings, and `04` shows the
official analog-pad terminals. The large raw RC decks are deliberately not
frozen; `input_rc_audit.json` binds their hashes and the extraction is fully
reproducible from the frozen GDS and checked-in scripts.

The next stage may only wrap this checkpoint with the official TinyTapeout top
cell and complete pin/label policy. It must not regenerate or edit any closed
analog, controller, input, output, bias, phase, or supply geometry.
