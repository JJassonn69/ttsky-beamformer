* Four-bit SKY130 R-2R ladder and matched CMOS bit drivers.
* R is the same 10.6 kohm high-poly unit already characterized in V1.
* Every 2R branch is two physical R units in series.

.subckt v2_r_unit a b bulk
XRU a b bulk sky130_fd_pr__res_high_po_1p41 l=44.9768
.ends v2_r_unit

.subckt v2_r2r_4bit b0 b1 b2 b3 out bulk
* LSB branch and 2R termination.
XR_B0A b0 b0m bulk v2_r_unit
XR_B0B b0m n0 bulk v2_r_unit
XR_T0A n0 t0m bulk v2_r_unit
XR_T0B t0m bulk bulk v2_r_unit

* Unit horizontal rung and bit-one branch.
XR_H01 n0 n1 bulk v2_r_unit
XR_B1A b1 b1m bulk v2_r_unit
XR_B1B b1m n1 bulk v2_r_unit

* Unit horizontal rung and bit-two branch.
XR_H12 n1 n2 bulk v2_r_unit
XR_B2A b2 b2m bulk v2_r_unit
XR_B2B b2m n2 bulk v2_r_unit

* Unit horizontal rung and MSB branch.
XR_H23 n2 out bulk v2_r_unit
XR_B3A b3 b3m bulk v2_r_unit
XR_B3B b3m out bulk v2_r_unit
.ends v2_r2r_4bit

.subckt v2_cmos_inv in out vdd vss params: wn=1.26 wp=2.0 l=0.15
XNI out in vss vss sky130_fd_pr__nfet_01v8 w={wn} l={l}
XPI out in vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l={l}
.ends v2_cmos_inv

.subckt v2_dac_bit_driver in out vdd vss
XI1 in mid vdd vss v2_cmos_inv wn=1.26 wp=2.0
XI2 mid out vdd vss v2_cmos_inv wn=2.52 wp=4.0
.ends v2_dac_bit_driver
