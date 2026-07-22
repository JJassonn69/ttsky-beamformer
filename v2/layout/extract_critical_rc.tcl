# Generate zero-pruning distributed-RC views of the V2 critical-route checkpoint.
set PROJECT_ROOT [pwd]
set WORKDIR [file join $PROJECT_ROOT build v2 critical_signal_routes magic]
set PCELL_DIR [file join $PROJECT_ROOT build v2 pcell_bbox_switched_tail_r5]
set CELL_DIR [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set SOURCE_TOP v2_four_channel_critical_routed
set TOP v2_four_channel_critical_routed_rc_flat
cd $WORKDIR

addpath $PCELL_DIR
foreach cell {mux2_1 and2_1 buf_4 inv_1 tapvpwrvgnd_1} {
    gds read [file join $CELL_DIR sky130_fd_sc_hd__${cell}.gds]
}

# Resistance extraction cannot reuse stale child or top annotations safely.
foreach stale [glob -nocomplain $WORKDIR/*.ext] {
    file delete -force $stale
}

load $SOURCE_TOP
select top cell
expand
# Extresist must see one continuous conductor graph.  Leaving PCells as
# hierarchy causes their port nodes to be re-identified with the unsplit
# parent net when ext2spice is written, bypassing the intended route segments.
flatten $TOP
load $TOP
select top cell
save $TOP
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CRITICAL_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing distributed-RC extraction of a layout with DRC errors"
}

extract do local
extresist threshold 0
extresist mindelay 0
extresist minres 0
extresist simplify off
extresist extout on
extract do resistance
extract all
set extract_feedback [feedback count]
puts "CRITICAL_RC_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save critical_route_rc_extraction_feedback.txt
    error "critical-route RC extraction produced $extract_feedback feedback item(s)"
}

ext2spice lvs
ext2spice hierarchy off
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice extresist off
set BASE_SPICE [file join $WORKDIR critical_routes_base.spice]
ext2spice -o $BASE_SPICE ${TOP}.ext

ext2spice extresist on
set RC_SPICE [file join $WORKDIR critical_routes_rc.spice]
ext2spice -o $RC_SPICE ${TOP}.ext

set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE_SPICE $RC_SPICE $RES_EXT] {
    if {![file exists $required]} {
        error "missing distributed-RC output: $required"
    }
}
puts "CRITICAL_BASE_SPICE=$BASE_SPICE"
puts "CRITICAL_RC_SPICE=$RC_SPICE"
puts "CRITICAL_RES_EXT=$RES_EXT"
quit -noprompt
