# Write fabrication views only after the final routed cell passes Magic DRC.
set PROJECT_ROOT [pwd]
set WORKDIR $PROJECT_ROOT/build/layout/buffered
set TOP tt_um_jjassonn69_beamformer
cd $WORKDIR

load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "SIGNOFF_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing to write fabrication files with DRC errors"
}

file mkdir $PROJECT_ROOT/gds
# TinyTapeout's precheck reads the .gds with gdstk, which does not infer gzip
# compression from a .gds suffix.  Emit a plain GDSII stream.
feedback clear
gds compress 0
gds write $PROJECT_ROOT/gds/$TOP.gds
set gds_feedback [feedback count]
feedback save $PROJECT_ROOT/build/gds_write_feedback.txt
puts "SIGNOFF_GDS_FEEDBACK_COUNT=$gds_feedback"
puts "SIGNOFF_GDS=$PROJECT_ROOT/gds/$TOP.gds"
if {$gds_feedback != 0} {
    error "refusing signoff: GDS writer reported $gds_feedback geometry problems"
}
quit -noprompt
