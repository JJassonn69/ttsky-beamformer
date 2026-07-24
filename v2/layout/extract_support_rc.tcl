# Generate zero-pruning distributed-RC views of the routed V2 support stage.
set PROJECT_ROOT [pwd]
set WORKDIR [file join $PROJECT_ROOT build v2 support_routes magic]
set PCELL_DIR [file join $PROJECT_ROOT build v2 pcell_bbox_remote]
set CELL_DIR [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set SOURCE_TOP v2_four_channel_support_routed
set TOP v2_four_channel_support_routed_rc_flat
set FORCE_ATTRIBUTES [file join $PROJECT_ROOT build v2 support_routes rc_force_attributes.tcl]
cd $WORKDIR

addpath $PCELL_DIR
foreach cell {mux2_1 and2_1 buf_4 inv_1 tapvpwrvgnd_1} {
    gds read [file join $CELL_DIR sky130_fd_sc_hd__${cell}.gds]
}

foreach stale [glob -nocomplain $WORKDIR/*.ext] {
    file delete -force $stale
}

load $SOURCE_TOP
select top cell
expand
# Route resistance must be extracted from one continuous conductor graph;
# otherwise hierarchical port aliases can bypass the intended metal segments.
flatten $TOP
load $TOP
select top cell
if {![file exists $FORCE_ATTRIBUTES]} {
    error "missing generated RC force-attribute file: $FORCE_ATTRIBUTES"
}
# Attributes are attached only to this temporary flattened extraction view.
# They do not alter or enter the manufactured GDS.
source $FORCE_ATTRIBUTES
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "SUPPORT_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing distributed-RC extraction of a layout with DRC errors"
}

extract unique notopports
extract do local
extract all
set extract_feedback [feedback count]
puts "SUPPORT_RC_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save support_route_rc_extraction_feedback.txt
    error "support-route RC extraction produced $extract_feedback feedback item(s)"
}

# Follow Magic's documented RCX sequence: ext2sim first creates the flattened
# node database consumed by extresist; extresist then writes the .res.ext graph.
ext2sim labels on
ext2sim

# Magic 8.3.676 correctly records res:drive@ as an attribute in TOP.ext, but
# its unfinished drivepoint-name fixup can reuse the literal label text as an
# electrical node when more than one such label remains in the edit cell.
# Re-create the exact same flattened conductor geometry without the temporary
# attribute labels before extresist walks it.  TOP.ext and TOP.nodes retain the
# intended per-net drive metadata; the layout used for node naming does not.
set CLEAN_TOP ${TOP}_clean
load $SOURCE_TOP
select top cell
expand
flatten $CLEAN_TOP
load $CLEAN_TOP
select top cell
cellname delete $TOP
cellname rename $CLEAN_TOP $TOP

extresist tolerance 10
extresist minres 0
extresist simplify off
extresist extout on
extresist

ext2spice lvs
ext2spice hierarchy off
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice extresist off
set BASE_SPICE [file join $WORKDIR support_routes_base.spice]
ext2spice -o $BASE_SPICE ${TOP}.ext

ext2spice extresist on
set RC_SPICE [file join $WORKDIR support_routes_rc.spice]
ext2spice -o $RC_SPICE ${TOP}.ext

set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE_SPICE $RC_SPICE $RES_EXT] {
    if {![file exists $required]} {
        error "missing distributed-RC output: $required"
    }
}
puts "SUPPORT_BASE_SPICE=$BASE_SPICE"
puts "SUPPORT_RC_SPICE=$RC_SPICE"
puts "SUPPORT_RES_EXT=$RES_EXT"
quit -noprompt
