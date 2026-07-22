# Full-chip DRC of the exact hierarchy-preserving control-power GDS.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 control_power direct v2_four_channel_control_powered.gds]
set OUT_DIR [file join $PROJECT_ROOT build v2 control_power direct magic]
file mkdir $OUT_DIR
if {![file exists $SOURCE_GDS]} {
    error "required assembled control-power GDS does not exist: $SOURCE_GDS"
}
gds readonly yes
gds read $SOURCE_GDS
if {[lsearch -exact [cellname list all] v2_four_channel_control_powered] < 0} {
    error "assembled control-power top cell was not imported"
}
load v2_four_channel_control_powered
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
set feedback_count [feedback count]
puts "CONTROL_POWER_DIRECT_GDS_DRC_COUNT=$drc_count"
puts "CONTROL_POWER_DIRECT_GDS_FEEDBACK_COUNT=$feedback_count"
if {$drc_count != 0 || $feedback_count != 0} {
    feedback save [file join $OUT_DIR control_power_direct_gds_feedback.txt]
    error "refusing assembled control-power GDS with DRC or import feedback"
}
cd $OUT_DIR
save v2_four_channel_control_powered.mag
puts "CONTROL_POWER_DIRECT_GDS_MAG_SAVED=1"
quit -noprompt
