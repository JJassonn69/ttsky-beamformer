* V3 Gate-2A one-channel constant-current Cartesian vector cell.
*
* This deliberately separates two questions:
*   1. Do the real SKY130 gm and commutating devices preserve the 1/2/4/8
*      complex-vector weighting selected by the architecture model?
*   2. How should the final MOS bias source be sized over PVT and mismatch?
*
* Gate 2A answers question 1 with one identical ideal tail-current source per
* unit slice. Replacing those sources with matched MOS sinks is the Gate-2B
* task. The ideal sources must never appear in a layout or submission netlist.

.subckt v3_vector_unit sig ref lop lon outp outn vss params: wgm=0.42 wsw=0.65 itail=6.6666667u
XGM_P gm_p sig tail vss sky130_fd_pr__nfet_01v8 w={wgm} l=0.30
XGM_N gm_n ref tail vss sky130_fd_pr__nfet_01v8 w={wgm} l=0.30

* Double-balanced NMOS commutating quad. Swapping lop/lon negates the
* coefficient without turning the slice off.
XSW_PP outp lop gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_PN outn lon gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NP outn lop gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NN outp lon gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
ITAIL tail vss {itail}
.ends v3_vector_unit

* Gate-2B replacement for the ideal source above. Fifteen 2.5333 um sinks
* have the same aggregate width as the proven V2 38 um mirror output while
* every vector state keeps all sinks enabled. A single shared resistor/diode
* reference is supplied by the testbench and, eventually, the top-level core.
.subckt v3_vector_unit_mos sig ref lop lon outp outn vbias vss params: wgm=0.42 wsw=0.65 wtail=2.533333333
XGM_P gm_p sig tail vss sky130_fd_pr__nfet_01v8 w={wgm} l=0.30
XGM_N gm_n ref tail vss sky130_fd_pr__nfet_01v8 w={wgm} l=0.30
XSW_PP outp lop gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_PN outn lon gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NP outn lop gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NN outp lon gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XTAIL tail vbias vss vss sky130_fd_pr__nfet_01v8 w={wtail} l=0.50
.ends v3_vector_unit_mos

* Four independently steered groups contain 1, 2, 4, and 8 identical units.
* All fifteen units are active for every valid word. Only the complementary
* LO pair connected to a group changes.
.subckt v3_vector_channel_15 sig ref
+ g0p g0n g1p g1n g2p g2n g3p g3n outp outn vss params: wgm=0.42 wsw=0.65 itail=6.6666667u
XG0_0 sig ref g0p g0n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}

XG1_0 sig ref g1p g1n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG1_1 sig ref g1p g1n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}

XG2_0 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG2_1 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG2_2 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG2_3 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}

XG3_0 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_1 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_2 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_3 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_4 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_5 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_6 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
XG3_7 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} wsw={wsw} itail={itail}
.ends v3_vector_channel_15

.subckt v3_vector_channel_15_mos sig ref
+ g0p g0n g1p g1n g2p g2n g3p g3n outp outn vbias vss params: wgm=0.42 wsw=0.65 wtail=2.533333333
XG0_0 sig ref g0p g0n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}

XG1_0 sig ref g1p g1n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG1_1 sig ref g1p g1n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}

XG2_0 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG2_1 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG2_2 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG2_3 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}

XG3_0 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_1 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_2 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_3 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_4 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_5 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_6 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
XG3_7 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} wsw={wsw} wtail={wtail}
.ends v3_vector_channel_15_mos
