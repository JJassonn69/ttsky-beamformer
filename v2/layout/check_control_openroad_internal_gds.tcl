# Full-chip DRC of the powered placement plus all 150 OpenROAD internal nets.
set PROJECT_ROOT [pwd]
set SOURCE_GDS [file join $PROJECT_ROOT build v2 control_routing openroad_internal direct v2_control_internal_routed.gds]
set TOP v2_control_internal_routed
set OUT_DIR [file join $PROJECT_ROOT build v2 control_routing openroad_internal magic]
file mkdir $OUT_DIR
if {![file exists $SOURCE_GDS]} { error "missing assembled internal-routed GDS" }
gds readonly yes
gds read $SOURCE_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} { error "internal-routed top was not imported" }
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set count [drc list count total]
set feedback_count [feedback count]
puts "CONTROL_INTERNAL_GDS_DRC_COUNT=$count"
puts "CONTROL_INTERNAL_GDS_FEEDBACK_COUNT=$feedback_count"
if {$count != 0 || $feedback_count != 0} {
    feedback save [file join $OUT_DIR control_internal_gds_feedback.txt]
    error "internal-routed GDS has DRC/import feedback"
}
cd $OUT_DIR
save ${TOP}.mag
puts "CONTROL_INTERNAL_GDS_MAG_SAVED=1"
quit -noprompt
