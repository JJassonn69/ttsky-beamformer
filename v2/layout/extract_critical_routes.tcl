# Extract the V2 critical-route checkpoint with the pinned SKY130 technology.
# This is a connectivity audit, not the eventual post-route RC signoff deck.
set PROJECT_ROOT [pwd]
set STAGE critical_signal_routes
if {[info exists ::env(V2_EXTRACT_STAGE)]} {
    set STAGE $::env(V2_EXTRACT_STAGE)
}
set WORKDIR [file join $PROJECT_ROOT build v2 $STAGE magic]
set PCELL_DIR [file join $PROJECT_ROOT build v2 pcell_bbox_switched_tail_r5]
set CELL_DIR [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set TOP v2_four_channel_critical_routed
if {[info exists ::env(V2_EXTRACT_TOP)]} {
    set TOP $::env(V2_EXTRACT_TOP)
}
set PREFIX critical_routes
if {[info exists ::env(V2_EXTRACT_PREFIX)]} {
    set PREFIX $::env(V2_EXTRACT_PREFIX)
}
cd $WORKDIR

# The saved top-level MAG references the original analog PCells and standard
# cells rather than flattening copies into this directory.  Make every child
# available before loading or extraction can silently skip an unavailable
# subtree while still returning a zero DRC count.
addpath $PCELL_DIR
foreach cell {mux2_1 and2_1 buf_4 inv_1 tapvpwrvgnd_1} {
    gds read [file join $CELL_DIR sky130_fd_sc_hd__${cell}.gds]
}

foreach stale [glob -nocomplain $WORKDIR/*.ext] {
    file delete -force $stale
}

load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CRITICAL_EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing to extract a critical-route checkpoint with DRC errors"
}

extract do local
extract all
set extract_feedback [feedback count]
puts "CRITICAL_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save critical_route_extraction_feedback.txt
    error "critical-route extraction produced $extract_feedback feedback item(s)"
}

ext2spice lvs
ext2spice hierarchy on
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
set HIER_SPICE [file join $WORKDIR ${PREFIX}_hier.spice]
ext2spice -o $HIER_SPICE ${TOP}.ext

ext2spice hierarchy off
set FLAT_SPICE [file join $WORKDIR ${PREFIX}_flat.spice]
ext2spice -o $FLAT_SPICE ${TOP}.ext
if {![file exists $HIER_SPICE] || ![file exists $FLAT_SPICE]} {
    error "critical-route netlist output is missing"
}
puts "CRITICAL_HIER_SPICE=$HIER_SPICE"
puts "CRITICAL_FLAT_SPICE=$FLAT_SPICE"
quit -noprompt
