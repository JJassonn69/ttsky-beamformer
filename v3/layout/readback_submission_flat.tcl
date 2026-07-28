# Flatten the exact packaged V3 GDS and extract using only official TT labels.
set PROJECT_ROOT [file normalize [pwd]]
if {[info exists ::env(V3_SUBMISSION_GDS)]} {
    set INPUT_GDS [file normalize $::env(V3_SUBMISSION_GDS)]
} else {
    set INPUT_GDS [file join $PROJECT_ROOT build v3 submission tt_um_jjassonn69_beamformer.gds]
}
if {[info exists ::env(V3_SUBMISSION_FLAT_DIR)]} {
    set WORKDIR [file normalize $::env(V3_SUBMISSION_FLAT_DIR)]
} else {
    set WORKDIR [file join $PROJECT_ROOT build v3 submission magic_flat]
}
if {[info exists ::env(V3_SUBMISSION_LABELS)]} {
    set LABEL_SCRIPT [file normalize $::env(V3_SUBMISSION_LABELS)]
} else {
    set LABEL_SCRIPT [file join $PROJECT_ROOT build v3 submission official_magic_labels.tcl]
}
set SOURCE_TOP tt_um_jjassonn69_beamformer
set TOP tt_um_jjassonn69_beamformer_magic_flat
if {![file exists $INPUT_GDS]} { error "missing packaged V3 submission GDS" }
if {![file exists $LABEL_SCRIPT]} { error "missing generated official-label script" }
file mkdir $WORKDIR
cd $WORKDIR
foreach stale [glob -nocomplain [file join $WORKDIR ${TOP}*]] { file delete -force $stale }
foreach stale [glob -nocomplain [file join $WORKDIR *_feedback.txt]] { file delete -force $stale }

gds readonly false
gds rescale false
gds read $INPUT_GDS
set gds_feedback [feedback count]
puts "V3_SUBMISSION_FLAT_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save [file join $WORKDIR gds_feedback.txt]
    error "Packaged V3 submission GDS produced import feedback"
}
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "Packaged V3 submission top $SOURCE_TOP was not imported"
}
load $SOURCE_TOP
select top cell
expand
flatten $TOP
load $TOP
select top cell
box 0.0um 0.0um 334.88um 225.76um
erase labels
source $LABEL_SCRIPT

drc euclidean on
if {[catch {drc style drc(full)} drc_style_error]} {
    error "Required sky130A drc(full) style is unavailable: $drc_style_error"
}
drc check
set drc_count [drc list count total]
puts "V3_SUBMISSION_FLAT_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    feedback save [file join $WORKDIR drc_feedback.txt]
    error "Flattened V3 submission has Magic DRC errors"
}

extract unique notopports
extract do local
extract all
set extraction_feedback [feedback count]
puts "V3_SUBMISSION_FLAT_EXTRACTION_FEEDBACK_COUNT=$extraction_feedback"
feedback save [file join $WORKDIR extraction_feedback.txt]
feedback clear
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o [file join $WORKDIR ${TOP}.spice] ${TOP}.ext
puts "V3_SUBMISSION_FLAT_FEEDBACK_AFTER_CLEAR=[feedback count]"
quit -noprompt
