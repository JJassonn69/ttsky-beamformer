# Independent Magic import, DRC, extraction, and GDS write for the routed V3
# selector.  The OpenROAD DEF is intentionally reconstructed from exact cell
# GDS, not trusted as the signoff artifact by itself.
set PROJECT_ROOT [file normalize [pwd]]
set WORKDIR [file normalize $::env(V3_SELECTOR_BUILD)]
set TECH_LEF [file normalize $::env(V3_SELECTOR_TECH_LEF)]
set CELL_ROOT [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set TOP v3_selector_route_pilot

cd $WORKDIR
catch {cellname delete $TOP}
lef read $TECH_LEF
foreach role {mux2_1 and2_1 and2b_1 tapvpwrvgnd_1 fill_1} {
    set stem sky130_fd_sc_hd__${role}
    lef read [file join $CELL_ROOT ${stem}.lef]
    gds read [file join $CELL_ROOT ${stem}.gds]
}
def read [file join $WORKDIR routed.def]
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_SELECTOR_ROUTE_MAGIC_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR magic_drc_feedback.txt]
    error "root-aligned selector has Magic DRC errors"
}

extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_SELECTOR_ROUTE_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
if {$extraction_feedback != 0} {
    feedback save [file join $WORKDIR magic_extraction_feedback.txt]
    error "root-aligned selector extraction has feedback"
}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}_flat.spice] ${TOP}.ext

feedback clear
gds write [file join $WORKDIR ${TOP}.gds]
puts "V3_SELECTOR_ROUTE_GDS_FEEDBACK_COUNT=[feedback count]"
quit -noprompt
