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

.subckt v3_vector_unit sig ref lop lon outp outn vss params: wgm=0.84 lgm=0.60 wsw=0.65 itail=6.6666667u
XGM_P gm_p sig tail vss sky130_fd_pr__nfet_01v8 w={wgm} l={lgm}
XGM_N gm_n ref tail vss sky130_fd_pr__nfet_01v8 w={wgm} l={lgm}

* Double-balanced NMOS commutating quad. Swapping lop/lon negates the
* coefficient without turning the slice off.
XSW_PP outp lop gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_PN outn lon gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NP outn lop gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NN outp lon gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
ITAIL tail vss {itail}
.ends v3_vector_unit

* Gate-2B replacement for the ideal source above.  The initial 0.42/0.30 um
* gm and 2.5333/0.50 um tail geometry missed the open-PDK mismatch target.
* Doubling W and L preserves each device's W/L while providing four times the
* matching area.  The 64/1.0 um shared diode reference preserves the tail-bank
* mirror ratio.  Every vector state keeps all sinks enabled.
.subckt v3_vector_unit_mos sig ref lop lon outp outn vbias vss params: wgm=0.84 lgm=0.60 wsw=0.65 wtail=5.066666666 ltail=1.00
XGM_P gm_p sig tail vss sky130_fd_pr__nfet_01v8 w={wgm} l={lgm}
XGM_N gm_n ref tail vss sky130_fd_pr__nfet_01v8 w={wgm} l={lgm}
XSW_PP outp lop gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_PN outn lon gm_p vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NP outn lop gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XSW_NN outp lon gm_n vss sky130_fd_pr__nfet_01v8 w={wsw} l=0.15
XTAIL tail vbias vss vss sky130_fd_pr__nfet_01v8 w={wtail} l={ltail}
.ends v3_vector_unit_mos

* Fabricatable interface between the shared analog bias and one channel's
* tail-gate bus.  ENABLE connects the reference to the capacitive local gate
* bus; BLANK actively discharges it.  Digital control must never assert both.
.subckt v3_bias_blank_switch vbias_ref enable blank vbias_local vss params: wpass=2.0 wpull=1.0
XPASS vbias_local enable vbias_ref vss sky130_fd_pr__nfet_01v8 w={wpass} l=0.15
XPULL vbias_local blank vss vss sky130_fd_pr__nfet_01v8 w={wpull} l=0.15
.ends v3_bias_blank_switch

* Four independently steered groups contain 1, 2, 4, and 8 identical units.
* All fifteen units are active for every valid word. Only the complementary
* LO pair connected to a group changes.
.subckt v3_vector_channel_15 sig ref
+ g0p g0n g1p g1n g2p g2n g3p g3n outp outn vss params: wgm=0.84 lgm=0.60 wsw=0.65 itail=6.6666667u
XG0_0 sig ref g0p g0n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}

XG1_0 sig ref g1p g1n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG1_1 sig ref g1p g1n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}

XG2_0 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG2_1 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG2_2 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG2_3 sig ref g2p g2n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}

XG3_0 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_1 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_2 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_3 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_4 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_5 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_6 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
XG3_7 sig ref g3p g3n outp outn vss v3_vector_unit params: wgm={wgm} lgm={lgm} wsw={wsw} itail={itail}
.ends v3_vector_channel_15

.subckt v3_vector_channel_15_mos sig ref
+ g0p g0n g1p g1n g2p g2n g3p g3n outp outn vbias vss params: wgm=0.84 lgm=0.60 wsw=0.65 wtail=5.066666666 ltail=1.00
XG0_0 sig ref g0p g0n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}

XG1_0 sig ref g1p g1n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG1_1 sig ref g1p g1n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}

XG2_0 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG2_1 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG2_2 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG2_3 sig ref g2p g2n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}

XG3_0 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_1 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_2 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_3 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_4 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_5 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_6 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
XG3_7 sig ref g3p g3n outp outn vbias vss v3_vector_unit_mos params: wgm={wgm} lgm={lgm} wsw={wsw} wtail={wtail} ltail={ltail}
.ends v3_vector_channel_15_mos
