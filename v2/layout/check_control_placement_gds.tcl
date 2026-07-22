# Re-import the hierarchy-preserving control-placement GDS and run full DRC.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_placement direct v2_four_channel_control_placed.gds]
set TOP v2_four_channel_control_placed
if {![file exists $INPUT_GDS]} {
    error "missing directly assembled control-placement GDS: $INPUT_GDS"
}
gds readonly no
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "assembled control-placement top cell was not imported"
}
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CONTROL_DIRECT_GDS_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $PROJECT_ROOT build v2 control_placement direct_gds_drc.txt]
    error "directly assembled control-placement GDS has $drc_count DRC errors"
}
puts "CONTROL_DIRECT_GDS_FEEDBACK_COUNT=[feedback count]"
quit -noprompt
