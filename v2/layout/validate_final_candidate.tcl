# Direct-GDS physical and topology gate for the current V2 candidate.
# Run from the repository root with the pinned SKY130A Magic rcfile.

set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_quadrature_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing quadrature_extraction]
set TOP v2_control_quadrature_routed
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing final candidate GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} {
    error "final candidate top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext] { file delete -force $stale }
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
set import_feedback [feedback count]
puts "CONTROL_QUADRATURE_EXTRACTION_DRC_COUNT=$drc_count"
puts "CONTROL_QUADRATURE_IMPORT_FEEDBACK_COUNT=$import_feedback"
if {$drc_count != 0 || $import_feedback != 0} {
    feedback save [file join $WORKDIR final_candidate_drc_feedback.txt]
    error "final candidate has DRC or import feedback"
}

extract do local
extract all
set extract_feedback [feedback count]
puts "CONTROL_QUADRATURE_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save [file join $WORKDIR final_candidate_extraction_feedback.txt]
    error "final candidate extraction produced feedback"
}

ext2spice lvs
ext2spice extresist off
ext2spice cthresh 1e99
ext2spice rthresh infinite
ext2spice hierarchy on
set HIER [file join $WORKDIR control_quadrature_hier.spice]
ext2spice -o $HIER ${TOP}.ext
ext2spice hierarchy off
set FLAT [file join $WORKDIR control_quadrature_flat.spice]
ext2spice -o $FLAT ${TOP}.ext
puts "CONTROL_QUADRATURE_HIER_SPICE=$HIER"
puts "CONTROL_QUADRATURE_FLAT_SPICE=$FLAT"
quit -noprompt
