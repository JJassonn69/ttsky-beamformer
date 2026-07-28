# Read back, DRC, and extract the exact packaged V3 TinyTapeout submission GDS.
set PROJECT_ROOT [file normalize [pwd]]
if {[info exists ::env(V3_SUBMISSION_GDS)]} {
    set INPUT_GDS [file normalize $::env(V3_SUBMISSION_GDS)]
} else {
    set INPUT_GDS [file join $PROJECT_ROOT build v3 submission tt_um_jjassonn69_beamformer.gds]
}
if {[info exists ::env(V3_SUBMISSION_READBACK_DIR)]} {
    set WORKDIR [file normalize $::env(V3_SUBMISSION_READBACK_DIR)]
} else {
    set WORKDIR [file join $PROJECT_ROOT build v3 submission magic_readback]
}
set TOP tt_um_jjassonn69_beamformer
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${TOP}*]] { file delete -force $stale }
foreach stale [glob -nocomplain [file join $WORKDIR *_feedback.txt]] { file delete -force $stale }
catch {cellname delete $TOP}
gds readonly false
gds rescale false
gds read $INPUT_GDS
set gds_feedback [feedback count]
puts "V3_SUBMISSION_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
    error "Packaged V3 submission GDS produced import feedback"
}
set imported_cells [cellname list all]
if {[lsearch -exact $imported_cells $TOP] < 0} {
    error "Packaged V3 submission top $TOP was not imported"
}
load $TOP
select top cell
expand
drc euclidean on
if {[catch {drc style drc(full)} drc_style_error]} {
    error "Required sky130A drc(full) style is unavailable: $drc_style_error"
}
drc check
set drc_count [drc list count total]
puts "V3_SUBMISSION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "Packaged V3 submission GDS has Magic DRC errors"
}
extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_SUBMISSION_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
feedback clear
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}_flat.spice] ${TOP}.ext
puts "V3_SUBMISSION_FEEDBACK_AFTER_CLEAR=[feedback count]"
quit -noprompt
