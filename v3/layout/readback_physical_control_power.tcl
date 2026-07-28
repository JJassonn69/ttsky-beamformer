# Read back and extract the exact direct-GDS V3 controller-power candidate.
set PROJECT_ROOT [file normalize [pwd]]
set INPUT_GDS [file join $PROJECT_ROOT build v3 control_power direct v3_four_channel_ctrl_powered.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 control_power magic_readback]
set TOP v3_four_channel_ctrl_powered
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${TOP}*]] { file delete -force $stale }
foreach stale [glob -nocomplain [file join $WORKDIR *_feedback.txt]] { file delete -force $stale }
catch {cellname delete $TOP}
gds readonly false
gds rescale false
gds read $INPUT_GDS
set gds_feedback [feedback count]
puts "V3_CONTROL_POWER_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
    error "V3 controller-power GDS produced import feedback"
}
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_CONTROL_POWER_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "V3 controller power has Magic DRC errors"
}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_CONTROL_POWER_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
feedback clear
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}_flat.spice] ${TOP}.ext
puts "V3_CONTROL_POWER_FEEDBACK_AFTER_CLEAR=[feedback count]"
quit -noprompt
