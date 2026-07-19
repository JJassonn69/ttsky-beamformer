* Conservative parameterized Tiny Tapeout analog interconnect envelope.
* The R and C limits are independently adjustable for mismatch sweeps.

.subckt tt_analog_path pad core params: rpath=500 cpath=5p
RPATH pad core {rpath}
CPATH core 0 {cpath}
.ends tt_analog_path
