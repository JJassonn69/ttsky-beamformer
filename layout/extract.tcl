# Extract the routed production cell with the pinned SKY130 Magic technology.
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
puts "EXTRACTION_DRC_COUNT=$drc_count"
if {$drc_count != 0} {
    error "refusing to extract a layout with DRC errors"
}

extract do local
extract all
set extract_feedback_count [feedback count]
puts "EXTRACTION_FEEDBACK_COUNT=$extract_feedback_count"
if {$extract_feedback_count != 0} {
    feedback save $PROJECT_ROOT/build/layout/extraction_feedback.tcl
    puts "EXTRACTION_FEEDBACK=$PROJECT_ROOT/build/layout/extraction_feedback.tcl"
}
ext2spice lvs
ext2spice hierarchy off
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice -o $PROJECT_ROOT/build/layout/extracted.spice $TOP.ext
puts "EXTRACTED_SPICE=$PROJECT_ROOT/build/layout/extracted.spice"
ext2spice cthresh 1e99
ext2spice -o $PROJECT_ROOT/build/layout/extracted_lvs.spice $TOP.ext
puts "EXTRACTED_LVS_SPICE=$PROJECT_ROOT/build/layout/extracted_lvs.spice"
quit -noprompt
