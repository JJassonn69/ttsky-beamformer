* Four-bit local tail-current trim for one V2 channel.
* Code 8 is nominal.  The fixed sink contributes 80% of nominal current;
* four binary-weighted sinks provide the 1/2/4/8-unit adjustment around it.

.subckt v2_trim_gate_switch code code_b gate vbias vss
* Static NMOS selectors are adequate here: vbias is about 0.7 V while the
* enable gate is 1.8 V, leaving ample pass-gate overdrive.  There is no DC
* load on the selected tail gate.
XON gate code vbias vss sky130_fd_pr__nfet_01v8 w=1.26 l=0.15
XOFF gate code_b vss vss sky130_fd_pr__nfet_01v8 w=1.26 l=0.15
.ends v2_trim_gate_switch

.subckt v2_tail_unit tail gate vss
XU tail gate vss vss sky130_fd_pr__nfet_01v8 w=1.26 l=0.50
.ends v2_tail_unit

.subckt v2_switched_tail_trim tail vbias c0 c0b c1 c1b c2 c2b c3 c3b vss
* All 47 current-sink fingers use the same 1.26 x 0.50 um unit geometry.
* Thirty-two always-on units establish the lower endpoint.  At default code
* 8, eight more units are active, for exactly 40 nominal units.  Physical
* PCells may group adjacent fingers, but extraction must recover 47 equal
* fingers rather than four unrelated transistor widths.
XM00 tail vbias vss v2_tail_unit
XM01 tail vbias vss v2_tail_unit
XM02 tail vbias vss v2_tail_unit
XM03 tail vbias vss v2_tail_unit
XM04 tail vbias vss v2_tail_unit
XM05 tail vbias vss v2_tail_unit
XM06 tail vbias vss v2_tail_unit
XM07 tail vbias vss v2_tail_unit
XM08 tail vbias vss v2_tail_unit
XM09 tail vbias vss v2_tail_unit
XM10 tail vbias vss v2_tail_unit
XM11 tail vbias vss v2_tail_unit
XM12 tail vbias vss v2_tail_unit
XM13 tail vbias vss v2_tail_unit
XM14 tail vbias vss v2_tail_unit
XM15 tail vbias vss v2_tail_unit
XM16 tail vbias vss v2_tail_unit
XM17 tail vbias vss v2_tail_unit
XM18 tail vbias vss v2_tail_unit
XM19 tail vbias vss v2_tail_unit
XM20 tail vbias vss v2_tail_unit
XM21 tail vbias vss v2_tail_unit
XM22 tail vbias vss v2_tail_unit
XM23 tail vbias vss v2_tail_unit
XM24 tail vbias vss v2_tail_unit
XM25 tail vbias vss v2_tail_unit
XM26 tail vbias vss v2_tail_unit
XM27 tail vbias vss v2_tail_unit
XM28 tail vbias vss v2_tail_unit
XM29 tail vbias vss v2_tail_unit
XM30 tail vbias vss v2_tail_unit
XM31 tail vbias vss v2_tail_unit
XS0 c0 c0b g0 vbias vss v2_trim_gate_switch
XS1 c1 c1b g1 vbias vss v2_trim_gate_switch
XS2 c2 c2b g2 vbias vss v2_trim_gate_switch
XS3 c3 c3b g3 vbias vss v2_trim_gate_switch

XT00 tail g0 vss v2_tail_unit

XT10 tail g1 vss v2_tail_unit
XT11 tail g1 vss v2_tail_unit

XT20 tail g2 vss v2_tail_unit
XT21 tail g2 vss v2_tail_unit
XT22 tail g2 vss v2_tail_unit
XT23 tail g2 vss v2_tail_unit

XT30 tail g3 vss v2_tail_unit
XT31 tail g3 vss v2_tail_unit
XT32 tail g3 vss v2_tail_unit
XT33 tail g3 vss v2_tail_unit
XT34 tail g3 vss v2_tail_unit
XT35 tail g3 vss v2_tail_unit
XT36 tail g3 vss v2_tail_unit
XT37 tail g3 vss v2_tail_unit
.ends v2_switched_tail_trim
