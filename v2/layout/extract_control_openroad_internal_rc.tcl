# Generate zero-pruning distributed-RC views of all 150 internal control nets.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing openroad_internal direct v2_control_internal_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing openroad_internal rc]
set SOURCE_TOP v2_control_internal_routed
set TOP v2_control_internal_routed_rc_flat
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact internal-routed GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "internal-routed top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes] {
    file delete -force $stale
}

load $SOURCE_TOP
select top cell
expand
# Metal resistance must be traced across cell boundaries, so RC extraction is
# deliberately performed on a temporary flat view of the exact release GDS.
flatten $TOP
load $TOP
select top cell
drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "CONTROL_INTERNAL_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} { error "refusing internal-route RCX with DRC errors" }

extract unique notopports
extract do local
extract all
set feedback_count [feedback count]
puts "CONTROL_INTERNAL_RC_EXTRACTION_FEEDBACK_COUNT=$feedback_count"
if {$feedback_count != 0} {
    feedback save control_internal_rc_extraction_feedback.txt
    error "internal-route RC extraction produced feedback"
}

# Magic's extresist flow requires the .nodes database produced by ext2sim.
ext2sim labels on
ext2sim
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
set BASE [file join $WORKDIR control_internal_base.spice]
ext2spice -o $BASE ${TOP}.ext
ext2spice extresist on
set RC [file join $WORKDIR control_internal_rc.spice]
ext2spice -o $RC ${TOP}.ext
set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE $RC $RES_EXT] {
    if {![file exists $required]} { error "missing distributed-RC output: $required" }
}
puts "CONTROL_INTERNAL_BASE_SPICE=$BASE"
puts "CONTROL_INTERNAL_RC_SPICE=$RC"
puts "CONTROL_INTERNAL_RES_EXT=$RES_EXT"
quit -noprompt
