# Measure compact, characterized SKY130 xhigh-poly input-bias candidates.
# This is a dimension/terminal-access study only; it creates no routed block.

set WORKDIR [file normalize "build/v3/input_bias_pcell_study_r2"]
file mkdir $WORKDIR
cd $WORKDIR
load v3_input_bias_pcell_study -silent

proc generate_and_report {label x generator parameters} {
    box ${x}um 0um ${x}um 0um
    set generated [eval magic::gencell $generator $label $parameters]
    puts "V3_INPUT_BIAS_PCELL $label $generated"
}

# Same 50-square electrical target as 1.41 um x 70.5 um.
generate_and_report XIN_0P35_L17P5_G 0 sky130::sky130_fd_pr__res_xhigh_po_0p35 \
    {l 17.5 m 1 guard 1 doports 1}
generate_and_report XIN_0P35_L17P5_U 10 sky130::sky130_fd_pr__res_xhigh_po_0p35 \
    {l 17.5 m 1 guard 0 doports 1}

# Three equal series segments retain 50 total squares and provide a fold
# option if the single 17.5 um body cannot close the routing keep-outs.
generate_and_report XIN_0P35_L5P833_G 20 sky130::sky130_fd_pr__res_xhigh_po_0p35 \
    {l 5.833333333 m 1 guard 1 doports 1}
generate_and_report XIN_0P35_L5P833_U 30 sky130::sky130_fd_pr__res_xhigh_po_0p35 \
    {l 5.833333333 m 1 guard 0 doports 1}

# 17.36 um compensates the width-dependent terminal resistance reported by
# the PCell, targeting the old 1.41 x 70.5 um device's 100.266 kohm value.
generate_and_report XIN_0P35_L17P36_G 40 sky130::sky130_fd_pr__res_xhigh_po_0p35 \
    {l 17.36 m 1 guard 1 doports 1}

save v3_input_bias_pcell_study.mag
writeall force
quit -noprompt
