# Full-chip DRC of the exact GDS after attaching the 16 trim-control routes.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_trim_routed.gds]
set TOP v2_control_trim_routed
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing direct magic]
file mkdir $OUT_DIR
if {![file exists $SOURCE_GDS]} {
    error "required assembled trim-routed GDS does not exist: $SOURCE_GDS"
}
gds readonly yes
gds read $SOURCE_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "assembled trim-routed top cell was not imported"
}
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
set feedback_count [feedback count]
puts "CONTROL_TRIM_DIRECT_GDS_DRC_COUNT=$drc_count"
puts "CONTROL_TRIM_DIRECT_GDS_FEEDBACK_COUNT=$feedback_count"
if {$drc_count != 0 || $feedback_count != 0} {
    feedback save [file join $OUT_DIR control_trim_direct_gds_feedback.txt]
    error "refusing trim-routed GDS with DRC or import feedback"
}
cd $OUT_DIR
save ${TOP}.mag
puts "CONTROL_TRIM_DIRECT_GDS_MAG_SAVED=1"
quit -noprompt
