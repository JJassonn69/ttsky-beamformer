# Generate representative V2 SKY130 PCells for exact bounding-box measurement.
# Run from the repository root with the pinned SKY130A Magic rcfile.

set WORKDIR [file normalize "build/v2/pcell_bbox_switched_tail_r5"]
file mkdir $WORKDIR
cd $WORKDIR

# Measurement must be reproducible and must not retain instances from an
# earlier PCell catalogue run.
file delete -force [file join $WORKDIR v2_pcell_bbox.mag]
catch {cellname delete v2_pcell_bbox}
load v2_pcell_bbox -silent

box 0um 0um 0um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XGM \
    w 1.6 l 0.30 nf 5 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

box 40um 0um 40um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XSW \
    w 1.6 l 0.15 nf 5 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

box 80um 0um 80um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTAIL \
    w 2.111111111 l 0.50 nf 9 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

box 120um 0um 120um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XDRVN \
    w 2.52 l 0.15 nf 1 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

box 150um 0um 150um 0um
magic::gencell sky130::sky130_fd_pr__pfet_01v8 XDRVP \
    w 4.0 l 0.15 nf 1 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

box 180um 0um 180um 0um
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 XR_GUARD \
    w 1.41 l 44.9768 m 1 guard 1 full_metal 1 doports 1

box 220um 0um 220um 0um
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 XR_UNIT \
    w 1.41 l 44.9768 m 1 guard 0 full_metal 1 doports 1

# Production-candidate local switched-tail bank.  These use a shared channel
# guard ring in the final placement, so the individual PCells are unguarded.
# Three identical 12-finger fixed groups provide 36 always-on units.  Together
# with the binary 1/2/4/8 bank, reset code 8 gives 44 active units.  Exact
# extracted-SPICE comparison against the prior 42+2 operating point showed
# 0.905 V output common mode while preserving coherent gain.
box 250um 0um 250um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_MAIN_THIRD \
    w 1.26 l 0.50 nf 12 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 280um 0um 280um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_B8 \
    w 1.26 l 0.50 nf 8 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 300um 0um 300um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_B4 \
    w 1.26 l 0.50 nf 4 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 315um 0um 315um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_B2 \
    w 1.26 l 0.50 nf 2 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 325um 0um 325um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_B1 \
    w 1.26 l 0.50 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 335um 0um 335um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XTRIM_SWITCH \
    w 1.26 l 0.15 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1

box 350um 0um 350um 0um
magic::gencell sky130::sky130_fd_pr__res_xhigh_po_1p41 XINPUT_BIAS \
    w 1.41 l 70.5 m 1 guard 1 full_metal 1 doports 1

box 380um 0um 380um 0um
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 XOUTPUT_LOAD \
    w 1.41 l 11.6117 m 1 guard 1 full_metal 1 doports 1

box 410um 0um 410um 0um
magic::gencell sky130::sky130_fd_pr__res_xhigh_po_1p41 XVCM_TOP \
    w 1.41 l 47.0 m 1 guard 1 full_metal 1 doports 1

box 440um 0um 440um 0um
magic::gencell sky130::sky130_fd_pr__res_xhigh_po_1p41 XVCM_BOTTOM \
    w 1.41 l 94.0 m 1 guard 1 full_metal 1 doports 1

box 470um 0um 470um 0um
magic::gencell sky130::sky130_fd_pr__cap_mim_m3_1 XVCM_CAP \
    w 22.0 l 22.0 nx 1 ny 1 doports 1

# Four identical compact LVT varactors provide the added VCM RF bypass.  The
# tiled implementation has materially higher simulated Q than one large square
# for the same aggregate capacitance, and preserves a symmetric placement.
box 550um 0um 550um 0um
magic::gencell sky130::sky130_fd_pr__cap_var_lvt XVCM_VAR \
    w 17.68 l 17.68 m 1 nf 1 guard 1 full_metal 1 doports 1

# One half of the shared diode-connected bias reference.  Two identical
# 16 um devices are placed with identical orientation and local routing.
# Nine fingers keep the cell compact while preserving the schematic's
# aggregate width exactly (9 * 1.7777777778 um = 16 um).
box 510um 0um 510um 0um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 XBIAS_DIODE \
    w 1.7777777778 l 0.50 nf 9 m 1 guard 1 conn_gates 1 full_metal 1 doports 1

save v2_pcell_bbox.mag
writeall force
quit -noprompt
