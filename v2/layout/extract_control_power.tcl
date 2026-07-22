# Extract topology from the exact assembled and import-clean control-power GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_power direct v2_four_channel_control_powered.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_power extraction]
set TOP v2_four_channel_control_powered
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} {
    error "missing exact assembled control-power GDS: $INPUT_GDS"
}
gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "assembled control-power top cell was not imported"
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
puts "CONTROL_POWER_EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing topology extraction with $drc_count DRC errors"
}

extract do local
extract all
set extract_feedback [feedback count]
puts "CONTROL_POWER_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save control_power_extraction_feedback.txt
    error "control-power extraction produced $extract_feedback feedback item(s)"
}

ext2spice lvs
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice hierarchy on
set HIER_SPICE [file join $WORKDIR control_power_hier.spice]
ext2spice -o $HIER_SPICE ${TOP}.ext
ext2spice hierarchy off
set FLAT_SPICE [file join $WORKDIR control_power_flat.spice]
ext2spice -o $FLAT_SPICE ${TOP}.ext
if {![file exists $HIER_SPICE] || ![file exists $FLAT_SPICE]} {
    error "control-power topology output is missing"
}
puts "CONTROL_POWER_HIER_SPICE=$HIER_SPICE"
puts "CONTROL_POWER_FLAT_SPICE=$FLAT_SPICE"
quit -noprompt
