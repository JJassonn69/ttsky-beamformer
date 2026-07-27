# Read back the URPM-repaired connected-input-bias GDS through Magic.
set PROJECT_ROOT [file normalize [pwd]]
set INPUT_GDS [file join $PROJECT_ROOT build v3 channel_input_bias_late_promotion v3_channel_input_bias_late_promotion.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_input_bias_late_promotion_readback]
set TOP v3_channel_input_bias_late_promotion
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${TOP}*]] { file delete -force $stale }
catch {cellname delete $TOP}
gds readonly false
gds rescale false
gds read $INPUT_GDS
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "final connected-input-bias GDS readback has DRC errors"
}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
if {$extraction_feedback != 9} {
    error "final GDS readback differs from the nine intentional shorted-dummy markers"
}
feedback clear
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}_readback.spice] ${TOP}.ext
puts "V3_CHANNEL_INPUT_BIAS_LATE_READBACK_FEEDBACK_AFTER_CLEAR=[feedback count]"
quit -noprompt
