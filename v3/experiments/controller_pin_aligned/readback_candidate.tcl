# Magic DRC and topology extraction for an isolated Candidate B checkpoint.
set PROJECT_ROOT [file normalize [pwd]]
foreach required {V3_CB_GDS V3_CB_TOP V3_CB_READBACK_DIR} {
    if {![info exists ::env($required)]} {
        error "missing required environment variable $required"
    }
}
set INPUT_GDS [file normalize $::env(V3_CB_GDS)]
set TOP $::env(V3_CB_TOP)
set WORKDIR [file normalize $::env(V3_CB_READBACK_DIR)]
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${TOP}*]] { file delete -force $stale }
foreach stale [glob -nocomplain [file join $WORKDIR *_feedback.txt]] { file delete -force $stale }
catch {cellname delete $TOP}
gds readonly false
gds rescale false
gds read $INPUT_GDS
set gds_feedback [feedback count]
puts "V3_CB_GDS_FEEDBACK_COUNT=$gds_feedback"
puts "V3_CONTROL_BOUNDARY_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
    error "Candidate B GDS produced import feedback"
}
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_CB_DRC_COUNT=$drc_count"
puts "V3_CONTROL_BOUNDARY_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "Candidate B GDS has Magic DRC errors"
}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_CB_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
puts "V3_CONTROL_BOUNDARY_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
feedback clear
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}_flat.spice] ${TOP}.ext
puts "V3_CB_FEEDBACK_AFTER_CLEAR=[feedback count]"
puts "V3_CONTROL_BOUNDARY_FEEDBACK_AFTER_CLEAR=[feedback count]"
quit -noprompt
