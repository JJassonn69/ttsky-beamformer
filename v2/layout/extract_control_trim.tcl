# Extract topology from the exact assembled trim-routed GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_trim_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing extraction]
set TOP v2_control_trim_routed
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} {
    error "missing exact assembled trim-routed GDS: $INPUT_GDS"
}
gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "assembled trim-routed top cell was not imported"
}
cd $WORKDIR
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
puts "CONTROL_TRIM_EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing trim topology extraction with $drc_count DRC errors"
}
extract do local
extract all
set extract_feedback [feedback count]
puts "CONTROL_TRIM_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save control_trim_extraction_feedback.txt
    error "trim extraction produced $extract_feedback feedback item(s)"
}
ext2spice lvs
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice hierarchy on
set HIER_SPICE [file join $WORKDIR control_trim_hier.spice]
ext2spice -o $HIER_SPICE ${TOP}.ext
puts "CONTROL_TRIM_HIER_SPICE=$HIER_SPICE"
quit -noprompt
