* Structurally symmetric four-phase selector for one V2 channel.
* A/B first-stage nodes are shared.  P and N final muxes swap A/B, so every
* selected path contains exactly two mux2 cells and the two outputs see the
* same cell and interconnect topology.

.include "third_party/sky130_fd_sc_hd_cells/sky130_fd_sc_hd__mux2_1.spice"
.include "third_party/sky130_fd_sc_hd_cells/sky130_fd_sc_hd__and2_1.spice"
.include "third_party/sky130_fd_sc_hd_cells/sky130_fd_sc_hd__buf_4.spice"

.subckt v2_phase_selector lo0 lo90 lo180 lo270 phase0 phase1 enable lop lon vdd vss
XMUX_A lo0 lo90 phase0 vss vss vdd vdd mux_a sky130_fd_sc_hd__mux2_1
XMUX_B lo180 lo270 phase0 vss vss vdd vdd mux_b sky130_fd_sc_hd__mux2_1
XMUX_P mux_a mux_b phase1 vss vss vdd vdd mux_p sky130_fd_sc_hd__mux2_1
XMUX_N mux_b mux_a phase1 vss vss vdd vdd mux_n sky130_fd_sc_hd__mux2_1

XGATE_P mux_p enable vss vss vdd vdd gate_p sky130_fd_sc_hd__and2_1
XGATE_N mux_n enable vss vss vdd vdd gate_n sky130_fd_sc_hd__and2_1
XBUF_P gate_p vss vss vdd vdd lop sky130_fd_sc_hd__buf_4
XBUF_N gate_n vss vss vdd vdd lon sky130_fd_sc_hd__buf_4
.ends v2_phase_selector
