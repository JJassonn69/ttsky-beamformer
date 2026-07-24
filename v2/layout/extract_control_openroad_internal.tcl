# Extract terminal-aware topology from the exact powered + OpenROAD-routed GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing openroad_internal direct v2_control_internal_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing openroad_internal extraction]
set TOP v2_control_internal_routed
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact internal-routed GDS" }
gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "internal-routed top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext] { file delete -force $stale }
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CONTROL_INTERNAL_EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} { error "internal-route topology extraction has DRC errors" }
extract do local
extract all
set feedback_count [feedback count]
puts "CONTROL_INTERNAL_EXTRACTION_FEEDBACK_COUNT=$feedback_count"
if {$feedback_count != 0} {
    feedback save control_internal_extraction_feedback.txt
    error "internal-route extraction produced feedback"
}
ext2spice lvs
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice hierarchy on
set HIER [file join $WORKDIR control_internal_hier.spice]
ext2spice -o $HIER ${TOP}.ext
ext2spice hierarchy off
set FLAT [file join $WORKDIR control_internal_flat.spice]
ext2spice -o $FLAT ${TOP}.ext
foreach required [list $HIER $FLAT] {
    if {![file exists $required]} { error "missing topology output: $required" }
}
puts "CONTROL_INTERNAL_HIER_SPICE=$HIER"
puts "CONTROL_INTERNAL_FLAT_SPICE=$FLAT"
quit -noprompt
