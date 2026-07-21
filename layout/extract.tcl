# Extract the routed production cell with the pinned SKY130 Magic technology.
set PROJECT_ROOT [pwd]
set WORKDIR $PROJECT_ROOT/build/layout/buffered
set TOP tt_um_jjassonn69_beamformer
cd $WORKDIR

# Resistance extraction is not safely incremental: an interrupted extresist
# run can leave a newer top .ext beside an older .res.ext, and Magic may try to
# reuse partial child annotations on the next invocation.  Remove only the
# generated extraction databases in this isolated work directory before the
# clean all-cell extraction below; source .mag layout is untouched.
foreach stale [glob -nocomplain $WORKDIR/*.ext] {
    file delete -force $stale
}

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

# Generate both the normal device/capacitance database and Magic's detailed
# route-resistance annotation.  ext2spice rthresh only filters resistors that
# already exist; `extract do resistance` is what creates the distributed
# .res.ext network in Magic >= 8.3.597.
extract do local
extresist threshold 0
extresist mindelay 0
# First generate a literal audit view: every extracted resistance, no segment
# floor and no topology reduction.
extresist minres 0
extresist simplify off
extresist extout on
extract do resistance
extract all
set extract_feedback_count [feedback count]
puts "EXTRACTION_FEEDBACK_COUNT=$extract_feedback_count"
if {$extract_feedback_count != 0} {
    feedback save $PROJECT_ROOT/build/layout/extraction_feedback.tcl
    puts "EXTRACTION_FEEDBACK=$PROJECT_ROOT/build/layout/extraction_feedback.tcl"
}
ext2spice lvs
ext2spice hierarchy off
ext2spice extresist off
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice -o $PROJECT_ROOT/build/layout/extracted.spice $TOP.ext
puts "EXTRACTED_SPICE=$PROJECT_ROOT/build/layout/extracted.spice"

# Literal zero-pruning distributed-RC simulation and audit view.
ext2spice extresist on
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice -o $PROJECT_ROOT/build/layout/extracted_rc.spice $TOP.ext
puts "EXTRACTED_RC_SPICE=$PROJECT_ROOT/build/layout/extracted_rc.spice"

# Keep a resistance-free, capacitance-suppressed view for topology/LVS checks.
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice -o $PROJECT_ROOT/build/layout/extracted_lvs.spice $TOP.ext
puts "EXTRACTED_LVS_SPICE=$PROJECT_ROOT/build/layout/extracted_lvs.spice"
quit -noprompt
