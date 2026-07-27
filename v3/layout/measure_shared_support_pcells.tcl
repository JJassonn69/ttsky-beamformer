# Measure the V3 shared-support passive PCell candidates under pinned Magic.
# This is a dimension/terminal catalogue only; it creates no routed GDS.

set WORKDIR [file normalize "build/v3/shared_support_pcell_measurements"]
file mkdir $WORKDIR
cd $WORKDIR
file delete -force [file join $WORKDIR v3_shared_support_pcell_measurement.mag]
catch {cellname delete v3_shared_support_pcell_measurement}
load v3_shared_support_pcell_measurement -silent

proc generate_and_report {label x generator parameters} {
    box ${x}um 0um ${x}um 0um
    set generated [eval magic::gencell $generator $label $parameters]
    puts "V3_SHARED_SUPPORT_PCELL $label $generated"
}

# Six identical units implement the VCM 2:4 common-centroid divider.  All
# three electrical scales are measured before the schematic tradeoff selects
# one; only the selected length may enter the routed pilot.
generate_and_report XVCM_UNIT_SCALE_1 0 sky130::sky130_fd_pr__res_xhigh_po_1p41 \
    {w 1.41 l 23.5 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XVCM_UNIT_SCALE_0P5 20 sky130::sky130_fd_pr__res_xhigh_po_1p41 \
    {w 1.41 l 11.75 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XVCM_UNIT_SCALE_0P25 40 sky130::sky130_fd_pr__res_xhigh_po_1p41 \
    {w 1.41 l 5.875 m 1 guard 1 full_metal 1 doports 1}

# Lower-sheet-resistance alternatives retain the same six-unit centroid
# topology.  Measure them now so an electrical winner can be placed without
# falling back to nominal or V2 dimensions.
generate_and_report XVCM_HIGH_UNIT_L5P875 250 sky130::sky130_fd_pr__res_high_po_1p41 \
    {w 1.41 l 5.875 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XVCM_HIGH_UNIT_L11P75 270 sky130::sky130_fd_pr__res_high_po_1p41 \
    {w 1.41 l 11.75 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XVCM_HIGH_UNIT_L23P5 290 sky130::sky130_fd_pr__res_high_po_1p41 \
    {w 1.41 l 23.5 m 1 guard 1 full_metal 1 doports 1}

generate_and_report XINPUT_BIAS 70 sky130::sky130_fd_pr__res_xhigh_po_1p41 \
    {w 1.41 l 70.5 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XOUTPUT_LOAD 100 sky130::sky130_fd_pr__res_high_po_1p41 \
    {w 1.41 l 11.6117 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XTAIL_BIAS_RESISTOR 130 sky130::sky130_fd_pr__res_high_po_1p41 \
    {w 1.41 l 44.9768 m 1 guard 1 full_metal 1 doports 1}
generate_and_report XDECAP_MIM 170 sky130::sky130_fd_pr__cap_mim_m3_1 \
    {w 22.0 l 22.0 nx 1 ny 1 doports 1}
generate_and_report XVCM_VAR 210 sky130::sky130_fd_pr__cap_var_lvt \
    {w 17.68 l 17.68 m 1 nf 1 guard 1 full_metal 1 doports 1}

# Some Magic PCell generators leave an empty scratch definition in the cell
# table.  It is not instantiated; remove it before writeall so a successful
# measurement log has no misleading "(UNNAMED)" write error.
catch {cellname delete {(UNNAMED)}}
save v3_shared_support_pcell_measurement.mag
writeall force
quit -noprompt
