# Generate endpoint-rooted distributed-RC views of the exact V3 vector unit.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 vector_unit_pilot v3_vector_unit_pilot.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 vector_unit_pilot rc]
set SOURCE_TOP v3_vector_unit_pilot
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact vector-unit pilot GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "vector-unit pilot top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes $WORKDIR/*.sim $WORKDIR/*.spice] {
    file delete -force $stale
}

# Coordinates include the pilot's fixed (20,20) um build origin.  Each view
# roots one electrically distinct conductor; transistor terminals keep all
# meaningful branches alive while extresist meshes the conductor geometry.
# Root the two GM conductors on their lower switch branches.  Their GM drain
# access points sit directly below the intentionally orthogonal M4 sig/ref
# feeds, and Magic assigns a zero-area label there to the upper layer.
set endpoints {
    {tail       20.785 22.975 met2}
    {gmp        20.500 29.435 met2}
    {gmn        22.360 29.435 met2}
    {outp       21.080 32.230 met3}
    {outn       21.780 32.230 met3}
    {lop_left   19.350 32.065 met3}
    {lon_left   19.350 30.035 met3}
    {lon_right  23.510 32.065 met3}
    {lop_right  23.510 30.035 met3}
    {sig        20.150 20.000 met4}
    {ref        22.710 20.000 met4}
    {vbias      21.430 20.000 met4}
}
foreach endpoint $endpoints {
    lassign $endpoint token root_x root_y root_layer
    set TOP v3_vector_unit_pilot_rc_${token}
    set CLEAN_TOP ${TOP}_clean

    load $SOURCE_TOP
    select top cell
    expand
    flatten $TOP
    load $TOP
    select top cell

    # Remove ordinary port labels so exactly one coordinate owns each RC root.
    box 15.0um 15.0um 30.0um 36.0um
    erase labels
    box ${root_x}um ${root_y}um ${root_x}um ${root_y}um
    label {res:drive@} FreeSans 0.10u -${root_layer}
    label {res:force@} FreeSans 0.10u -${root_layer}

    drc euclidean on
    drc style drc(full)
    drc check
    set drc_count [drc list count total]
    puts "V3_VECTOR_UNIT_RC_DRC_COUNT_${token}=$drc_count"
    if {$drc_count != 0} { error "refusing $token vector-unit RCX with DRC errors" }

    extract unique notopports
    extract do local
    extract all
    set feedback_count [feedback count]
    puts "V3_VECTOR_UNIT_RC_EXTRACTION_FEEDBACK_COUNT_${token}=$feedback_count"
    if {$feedback_count != 0} {
        feedback save [file join $WORKDIR extraction_feedback_${token}.txt]
        error "$token vector-unit RC extraction produced feedback"
    }
    ext2sim labels on
    ext2sim

    # Recreate a label-clean exact-GDS view before conductor meshing.  The
    # .nodes database above retains the computational drive metadata.
    load $SOURCE_TOP
    select top cell
    expand
    flatten $CLEAN_TOP
    load $CLEAN_TOP
    select top cell
    box 15.0um 15.0um 30.0um 36.0um
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
    set BASE [file join $WORKDIR vector_unit_${token}_base.spice]
    ext2spice -o $BASE ${TOP}.ext
    ext2spice extresist on
    set RC [file join $WORKDIR vector_unit_${token}_rc.spice]
    ext2spice -o $RC ${TOP}.ext
    set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
    foreach required [list $BASE $RC $RES_EXT] {
        if {![file exists $required]} { error "missing $token distributed-RC output: $required" }
    }
    puts "V3_VECTOR_UNIT_BASE_SPICE_${token}=$BASE"
    puts "V3_VECTOR_UNIT_RC_SPICE_${token}=$RC"
    puts "V3_VECTOR_UNIT_RES_EXT_${token}=$RES_EXT"
}
quit -noprompt
