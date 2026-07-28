# Generate endpoint-rooted distributed-RC views of the exact V3 reference pilot.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 tail_reference_pilot v3_tail_reference_pilot.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 tail_reference_pilot rc]
set SOURCE_TOP v3_tail_reference_pilot
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact tail-reference pilot GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "tail-reference pilot top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes] {
    file delete -force $stale
}

# One extraction is rooted at each channel leaf.  Magic legitimately prunes
# open conductor branches that have no device or drive point, so one shared
# extraction cannot prove four independent leaf endpoints.  These four
# temporary views all use the exact same manufactured GDS geometry.
set endpoints {
    {common 123.28 111.00}
    {ch0 152.26 102.00}
    {ch1 132.94 102.00}
    {ch2 113.62 102.00}
    {ch3 94.30 102.00}
}
foreach endpoint $endpoints {
    lassign $endpoint token leaf_x leaf_y
    set TOP v3_tail_reference_pilot_rc_${token}
    set CLEAN_TOP ${TOP}_clean

    load $SOURCE_TOP
    select top cell
    expand
    flatten $TOP
    load $TOP
    select top cell

    # Remove the ordinary vbias_ref net label from this temporary view before
    # choosing a unique RC root.  Keeping it as well as res:drive@ would give
    # one SPICE node name to two physical coordinates and could hide series R.
    box 193.70um 51.90um 194.30um 52.50um
    erase labels
    box ${leaf_x}um ${leaf_y}um ${leaf_x}um ${leaf_y}um
    label {res:drive@} FreeSans 0.10u -met2
    label {res:force@} FreeSans 0.10u -met2

    drc euclidean on
    drc style drc(full)
    drc check
    set drc_count [drc list count total]
    puts "V3_TAIL_REFERENCE_RC_DRC_COUNT_${token}=$drc_count"
    if {$drc_count != 0} { error "refusing $token tail-reference RCX with DRC errors" }

    extract unique notopports
    extract do local
    extract all
    set feedback_count [feedback count]
    puts "V3_TAIL_REFERENCE_RC_EXTRACTION_FEEDBACK_COUNT_${token}=$feedback_count"
    if {$feedback_count != 0} {
        feedback save [file join $WORKDIR extraction_feedback_${token}.txt]
        error "$token tail-reference RC extraction produced feedback"
    }
    ext2sim labels on
    ext2sim

    # Return to a label-clean flat view of the exact GDS before conductor
    # meshing.  The .nodes database retains the computational drive metadata.
    load $SOURCE_TOP
    select top cell
    expand
    flatten $CLEAN_TOP
    load $CLEAN_TOP
    select top cell
    box 193.70um 51.90um 194.30um 52.50um
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
    set BASE [file join $WORKDIR tail_reference_${token}_base.spice]
    ext2spice -o $BASE ${TOP}.ext
    ext2spice extresist on
    set RC [file join $WORKDIR tail_reference_${token}_rc.spice]
    ext2spice -o $RC ${TOP}.ext
    set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
    foreach required [list $BASE $RC $RES_EXT] {
        if {![file exists $required]} { error "missing $token distributed-RC output: $required" }
    }
    puts "V3_TAIL_REFERENCE_BASE_SPICE_${token}=$BASE"
    puts "V3_TAIL_REFERENCE_RC_SPICE_${token}=$RC"
    puts "V3_TAIL_REFERENCE_RES_EXT_${token}=$RES_EXT"
}
quit -noprompt
