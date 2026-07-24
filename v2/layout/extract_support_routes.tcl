# Extract the routed V2 VCM/bias support checkpoint with the pinned SKY130 PDK.
# This produces both hierarchical and flat, capacitance-suppressed topology
# views.  Distributed resistance is handled by the later RC signoff stage.
set PROJECT_ROOT [pwd]
set WORKDIR [file join $PROJECT_ROOT build v2 support_routes magic]
set PCELL_DIR [file join $PROJECT_ROOT build v2 pcell_bbox_remote]
set CELL_DIR [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set TOP v2_four_channel_support_routed
cd $WORKDIR

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
puts "SUPPORT_EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing to extract a support checkpoint with DRC errors"
}

extract do local
extract all
set extract_feedback [feedback count]
puts "SUPPORT_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save support_route_extraction_feedback.txt
    error "support-route extraction produced $extract_feedback feedback item(s)"
}

ext2spice lvs
ext2spice hierarchy on
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
set HIER_SPICE [file join $WORKDIR support_routes_hier.spice]
ext2spice -o $HIER_SPICE ${TOP}.ext

ext2spice hierarchy off
set FLAT_SPICE [file join $WORKDIR support_routes_flat.spice]
ext2spice -o $FLAT_SPICE ${TOP}.ext
if {![file exists $HIER_SPICE] || ![file exists $FLAT_SPICE]} {
    error "support-route netlist output is missing"
}
puts "SUPPORT_HIER_SPICE=$HIER_SPICE"
puts "SUPPORT_FLAT_SPICE=$FLAT_SPICE"
quit -noprompt
