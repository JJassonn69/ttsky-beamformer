# Generate zero-pruning distributed-RC views from the exact final control GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_service_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing control_service_rc]
set SOURCE_TOP v2_control_service_routed
set TOP v2_control_service_routed_rc_flat
set FORCE_ATTRIBUTES [file join $WORKDIR force_attributes.tcl]
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact final control GDS" }
if {![file exists $FORCE_ATTRIBUTES]} { error "missing control RC force attributes" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "final control top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes] {
    file delete -force $stale
}

load $SOURCE_TOP
select top cell
expand
flatten $TOP
load $TOP
select top cell
# These labels exist only in this temporary extraction view.  They force the
# four externally driven clocks/reset/config inputs into the resistor graph.
source $FORCE_ATTRIBUTES
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CONTROL_SERVICE_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} { error "refusing final-control RCX with DRC errors" }

extract unique notopports
extract do local
extract all
set extract_feedback [feedback count]
puts "CONTROL_SERVICE_RC_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save control_service_rc_extraction_feedback.txt
    error "final-control RC extraction produced feedback"
}

# Magic's documented sequence requires a flattened .nodes database before
# extresist writes the distributed .res.ext graph.
ext2sim labels on
ext2sim

# Remove temporary attribute labels from the layout used by extresist while
# retaining the drive metadata already written into TOP.ext/TOP.nodes.
set CLEAN_TOP ${TOP}_clean
load $SOURCE_TOP
select top cell
expand
flatten $CLEAN_TOP
load $CLEAN_TOP
select top cell
cellname delete $TOP
cellname rename $CLEAN_TOP $TOP

extresist threshold 0
extresist mindelay 0
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
set BASE_SPICE [file join $WORKDIR control_service_base.spice]
ext2spice -o $BASE_SPICE ${TOP}.ext

ext2spice extresist on
set RC_SPICE [file join $WORKDIR control_service_rc.spice]
ext2spice -o $RC_SPICE ${TOP}.ext

set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE_SPICE $RC_SPICE $RES_EXT] {
    if {![file exists $required]} { error "missing distributed-RC output: $required" }
}
puts "CONTROL_SERVICE_BASE_SPICE=$BASE_SPICE"
puts "CONTROL_SERVICE_RC_SPICE=$RC_SPICE"
puts "CONTROL_SERVICE_RES_EXT=$RES_EXT"
quit -noprompt
