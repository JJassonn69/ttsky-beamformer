# Generate endpoint-rooted distributed-RC views of all eight V3 phase trees.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 channel_phase_tree_pilot v3_channel_phase_tree_pilot.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_phase_tree_pilot rc]
set SOURCE_TOP v3_channel_phase_tree_pilot
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact channel-phase-tree pilot GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "channel-phase-tree pilot top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes $WORKDIR/*.sim $WORKDIR/*.spice] {
    file delete -force $stale
}

# Coordinates include the pilot's fixed (20,20) um build origin.
set endpoints {
    {g1_lop 24.87 113.05 met4}
    {g1_lon 30.87 113.05 met4}
    {g2_lon 38.47 113.05 met4}
    {g2_lop 39.12 113.05 met4}
    {g4_lon 37.17 113.05 met4}
    {g4_lop 37.82 113.05 met4}
    {g8_lop 36.52 113.05 met4}
    {g8_lon 35.82 113.05 met4}
}
foreach endpoint $endpoints {
    lassign $endpoint token root_x root_y root_layer
    set TOP v3_channel_phase_tree_pilot_rc_${token}
    set CLEAN_TOP ${TOP}_clean

    load $SOURCE_TOP
    select top cell
    expand
    flatten $TOP
    load $TOP
    select top cell

    # Exactly one coordinate owns the computational drive root in each view.
    box 15.0um 15.0um 45.0um 120.0um
    erase labels
    box ${root_x}um ${root_y}um ${root_x}um ${root_y}um
    label {res:drive@} FreeSans 0.10u -${root_layer}
    label {res:force@} FreeSans 0.10u -${root_layer}

    drc euclidean on
    drc style drc(full)
    drc check
    set drc_count [drc list count total]
    puts "V3_CHANNEL_PHASE_TREE_RC_DRC_COUNT_${token}=$drc_count"
    if {$drc_count != 0} { error "refusing $token phase-tree RCX with DRC errors" }

    extract unique notopports
    extract do local
    extract all
    set feedback_count [feedback count]
    puts "V3_CHANNEL_PHASE_TREE_RC_EXTRACTION_FEEDBACK_COUNT_${token}=$feedback_count"
    if {$feedback_count != 0} {
        feedback save [file join $WORKDIR extraction_feedback_${token}.txt]
        error "$token phase-tree RC extraction produced feedback"
    }
    ext2sim labels on
    ext2sim

    # Mesh a label-clean copy of the exact GDS.  The .nodes database above
    # retains the drive coordinate used by extresist.
    load $SOURCE_TOP
    select top cell
    expand
    flatten $CLEAN_TOP
    load $CLEAN_TOP
    select top cell
    box 15.0um 15.0um 45.0um 120.0um
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
    set BASE [file join $WORKDIR phase_tree_${token}_base.spice]
    ext2spice -o $BASE ${TOP}.ext
    ext2spice extresist on
    set RC [file join $WORKDIR phase_tree_${token}_rc.spice]
    ext2spice -o $RC ${TOP}.ext
    set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
    foreach required [list $BASE $RC $RES_EXT] {
        if {![file exists $required]} { error "missing $token distributed-RC output: $required" }
    }
    puts "V3_CHANNEL_PHASE_TREE_BASE_SPICE_${token}=$BASE"
    puts "V3_CHANNEL_PHASE_TREE_RC_SPICE_${token}=$RC"
    puts "V3_CHANNEL_PHASE_TREE_RES_EXT_${token}=$RES_EXT"
}
quit -noprompt
