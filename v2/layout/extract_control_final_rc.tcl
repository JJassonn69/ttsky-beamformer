# Generate zero-pruning distributed-RC views of the exact complete V2 GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_quadrature_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing final_rc]
set SOURCE_TOP v2_control_quadrature_routed
set TOP v2_control_final_rc_flat
set FORCE_ATTRIBUTES [file join $WORKDIR force_attributes.tcl]
if {[info exists ::env(BF_RC_GDS)]} {
    set INPUT_GDS [file normalize $::env(BF_RC_GDS)]
}
if {[info exists ::env(BF_RC_WORKDIR)]} {
    set WORKDIR [file normalize $::env(BF_RC_WORKDIR)]
}
if {[info exists ::env(BF_RC_SOURCE_TOP)]} {
    set SOURCE_TOP $::env(BF_RC_SOURCE_TOP)
}
if {[info exists ::env(BF_RC_FLAT_TOP)]} {
    set TOP $::env(BF_RC_FLAT_TOP)
}
if {[info exists ::env(BF_RC_ATTRIBUTES)]} {
    set FORCE_ATTRIBUTES [file normalize $::env(BF_RC_ATTRIBUTES)]
}
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact complete V2 GDS" }
if {![file exists $FORCE_ATTRIBUTES]} { error "missing final RC force attributes" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "complete V2 top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes] {
    file delete -force $stale
}

load $SOURCE_TOP
select top cell
expand
flatten $TOP
load $TOP
select top cell
source $FORCE_ATTRIBUTES
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CONTROL_FINAL_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} { error "refusing complete V2 RCX with DRC errors" }

extract unique notopports
extract do local
extract all
set extract_feedback [feedback count]
puts "CONTROL_FINAL_RC_EXTRACTION_FEEDBACK_COUNT=$extract_feedback"
if {$extract_feedback != 0} {
    feedback save control_final_rc_extraction_feedback.txt
    error "complete V2 RC extraction produced feedback"
}

ext2sim labels on
ext2sim

# Remove temporary attributes from layout geometry after their drive metadata
# has been written into TOP.ext/TOP.nodes, before distributed resistance runs.
set CLEAN_TOP ${TOP}_clean
load $SOURCE_TOP
select top cell
expand
flatten $CLEAN_TOP
load $CLEAN_TOP
select top cell
cellname delete $TOP
cellname rename $CLEAN_TOP $TOP

extresist threshold 0
extresist mindelay 0
extresist tolerance 10
extresist minres 0
extresist simplify off
extresist extout on
extresist

ext2spice lvs
ext2spice hierarchy off
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice extresist off
set BASE_SPICE [file join $WORKDIR control_final_base.spice]
ext2spice -o $BASE_SPICE ${TOP}.ext
ext2spice extresist on
set RC_SPICE [file join $WORKDIR control_final_rc.spice]
ext2spice -o $RC_SPICE ${TOP}.ext
set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE_SPICE $RC_SPICE $RES_EXT] {
    if {![file exists $required]} { error "missing complete distributed-RC output: $required" }
}
puts "CONTROL_FINAL_BASE_SPICE=$BASE_SPICE"
puts "CONTROL_FINAL_RC_SPICE=$RC_SPICE"
puts "CONTROL_FINAL_RES_EXT=$RES_EXT"
quit -noprompt
