# Generate a distributed-RC view of the exact V3 VCM support pilot.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 vcm_support_pilot v3_vcm_support_pilot.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 vcm_support_pilot rc]
set SOURCE_TOP v3_vcm_support_pilot
set TOP v3_vcm_support_pilot_rc
set CLEAN_TOP ${TOP}_clean
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact VCM support pilot GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "VCM support pilot top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes] {
    file delete -force $stale
}

# Root conductor meshing at the external VCM handoff.  The divider star and
# all three MIM top plates terminate the same routed conductor through real
# devices, so one endpoint-rooted view retains every branch we need to audit.
load $SOURCE_TOP
select top cell
expand
flatten $TOP
load $TOP
select top cell
box 113.20um 89.60um 114.05um 90.40um
erase labels
box 113.62um 90.00um 113.62um 90.00um
label {res:drive@} FreeSans 0.10u -met4
label {res:force@} FreeSans 0.10u -met4

drc euclidean on
drc style drc(full)
drc check
set drc_count [drc list count total]
puts "V3_VCM_SUPPORT_RC_DRC_COUNT=$drc_count"
if {$drc_count != 0} { error "refusing VCM support RCX with DRC errors" }

extract unique notopports
extract do local
extract all
set feedback_count [feedback count]
puts "V3_VCM_SUPPORT_RC_EXTRACTION_FEEDBACK_COUNT=$feedback_count"
if {$feedback_count != 0} {
    feedback save [file join $WORKDIR extraction_feedback.txt]
    error "VCM support RC extraction produced feedback"
}
ext2sim labels on
ext2sim

# Mesh a label-clean flat view of the exact GDS.  The .nodes database created
# above retains the computational drive metadata without renaming two physical
# points on the routed net to the same SPICE node.
load $SOURCE_TOP
select top cell
expand
flatten $CLEAN_TOP
load $CLEAN_TOP
select top cell
box 113.20um 89.60um 114.05um 90.40um
erase labels
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
set BASE [file join $WORKDIR vcm_support_base.spice]
ext2spice -o $BASE ${TOP}.ext
ext2spice extresist on
set RC [file join $WORKDIR vcm_support_rc.spice]
ext2spice -o $RC ${TOP}.ext
set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
foreach required [list $BASE $RC $RES_EXT] {
    if {![file exists $required]} { error "missing VCM distributed-RC output: $required" }
}
puts "V3_VCM_SUPPORT_BASE_SPICE=$BASE"
puts "V3_VCM_SUPPORT_RC_SPICE=$RC"
puts "V3_VCM_SUPPORT_RES_EXT=$RES_EXT"
quit -noprompt
