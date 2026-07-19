# SPDX-License-Identifier: Apache-2.0
# Noninteractive smoke test for the SKY130 Magic parameterized devices used by
# the beamformer. This deliberately writes only into build/layout-smoke.

set OUTDIR build/layout-smoke
file mkdir $OUTDIR

load tt_beamformer_pdk_smoke -silent
box 10um 10um 10um 10um

magic::gencell sky130::sky130_fd_pr__nfet_01v8 MN_TEST \
    w 1.0 l 0.30 nf 8 m 1 guard 1 doports 1

box 20um 10um 20um 10um
magic::gencell sky130::sky130_fd_pr__nfet_01v8 MN_M_TEST \
    w 1.0 l 0.30 nf 1 m 8 guard 1 doports 1

box 30um 10um 30um 10um
magic::gencell sky130::sky130_fd_pr__pfet_01v8 MP_TEST \
    w 2.0 l 0.15 nf 8 m 1 guard 1 doports 1

box 55um 10um 55um 10um
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 RH_TEST \
    w 1.41 l 11.6117 m 1 guard 1 doports 1

box 75um 10um 75um 10um
magic::gencell sky130::sky130_fd_pr__res_xhigh_po_1p41 RXH_TEST \
    w 1.41 l 70.5 m 1 guard 1 doports 1

box 105um 10um 105um 10um
magic::gencell sky130::sky130_fd_pr__cap_mim_m3_1 CMIM_TEST \
    w 22.0 l 22.0 nx 1 ny 1 doports 1

save $OUTDIR/tt_beamformer_pdk_smoke.mag
writeall force

foreach inst {MN_TEST MN_M_TEST MP_TEST RH_TEST RXH_TEST CMIM_TEST} {
    set child [instance list celldef $inst]
    puts "PCELL $inst cell=$child"
}

select top cell
expand
extract do local
extract all
ext2spice lvs
ext2spice subcircuit on
ext2spice -o $OUTDIR/tt_beamformer_pdk_smoke.spice

drc euclidean on
drc check
set drc_count [drc list count total]
puts "PDK_SMOKE_DRC_COUNT=$drc_count"

gds write $OUTDIR/tt_beamformer_pdk_smoke.gds
quit -noprompt
