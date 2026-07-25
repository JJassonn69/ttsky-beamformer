# V3 Gate-3 dimension study only.  This does not create a channel layout or GDS.
# Run with the same pinned SKY130A Magic rcfile used by the frozen V2 evidence.

set WORKDIR [file normalize "v3_pcell_measurement"]
file mkdir $WORKDIR
cd $WORKDIR
load v3_pcell_measurement -silent

proc generate_and_report {label x generator parameters} {
    box ${x}um 0um ${x}um 0um
    set generated [eval magic::gencell $generator $label $parameters]
    puts "V3_PCELL $label $generated"
}

# Unguarded unit-array devices; the final channel must use one shared guard.
generate_and_report XGM_U 0 sky130::sky130_fd_pr__nfet_01v8 \
    {w 0.84 l 0.60 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1}
generate_and_report XSW_U 20 sky130::sky130_fd_pr__nfet_01v8 \
    {w 0.65 l 0.15 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1}
generate_and_report XTAIL_U 40 sky130::sky130_fd_pr__nfet_01v8 \
    {w 5.066666666 l 1.00 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1}

# Guarded references bound the cost if unit-level guards prove necessary.
generate_and_report XGM_G 60 sky130::sky130_fd_pr__nfet_01v8 \
    {w 0.84 l 0.60 nf 1 m 1 guard 1 conn_gates 1 full_metal 1 doports 1}
generate_and_report XSW_G 80 sky130::sky130_fd_pr__nfet_01v8 \
    {w 0.65 l 0.15 nf 1 m 1 guard 1 conn_gates 1 full_metal 1 doports 1}
generate_and_report XTAIL_G 100 sky130::sky130_fd_pr__nfet_01v8 \
    {w 5.066666666 l 1.00 nf 1 m 1 guard 1 conn_gates 1 full_metal 1 doports 1}

# Per-channel fabricatable tail-bias pass/pulldown interface.
generate_and_report XBIAS_PASS_U 120 sky130::sky130_fd_pr__nfet_01v8 \
    {w 2.0 l 0.15 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1}
generate_and_report XBIAS_PULL_U 140 sky130::sky130_fd_pr__nfet_01v8 \
    {w 1.0 l 0.15 nf 1 m 1 guard 0 conn_gates 1 full_metal 1 doports 1}

save v3_pcell_measurement.mag
writeall force
quit -noprompt
