# Generate pad-rooted distributed-RC views of the integrated differential outputs.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 four_channel_output_load_integration v3_four_channel_output_load_integration.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 four_channel_output_load_integration rc]
set SOURCE_TOP v3_four_channel_output_load_integration
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing V3 output-load integration GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "V3 output-load integration top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes $WORKDIR/*.sim $WORKDIR/*.spice] {
    file delete -force $stale
}

set endpoints {
    {p 74.98 0.50 met4}
    {n 55.66 0.50 met4}
}
foreach endpoint $endpoints {
    lassign $endpoint token root_x root_y root_layer
    set TOP v3_four_channel_output_load_rc_${token}
    set CLEAN_TOP ${TOP}_clean

    load $SOURCE_TOP
    select top cell
    expand
    flatten $TOP
    load $TOP
    select top cell
    box 0.0um 0.0um 334.88um 225.76um
    erase labels
    box ${root_x}um ${root_y}um ${root_x}um ${root_y}um
    label {res:drive@} FreeSans 0.10u -${root_layer}
    label {res:force@} FreeSans 0.10u -${root_layer}

    drc euclidean on
    drc style drc(full)
    drc check
    set drc_count [drc list count total]
    puts "V3_FOUR_CHANNEL_OUTPUT_RC_DRC_COUNT_${token}=$drc_count"
    if {$drc_count != 0} { error "refusing $token output RCX with DRC errors" }

    extract unique notopports
    extract do local
    extract all
    set feedback_count [feedback count]
    puts "V3_FOUR_CHANNEL_OUTPUT_RC_EXTRACTION_FEEDBACK_COUNT_${token}=$feedback_count"
    # Flattening expands the nine qualified grounded edge dummies in the
    # frozen channel macro into four physical copies: 4 x 9 = 36 notices.
    if {$feedback_count != 36} {
        feedback save [file join $WORKDIR extraction_feedback_${token}.txt]
        error "$token output extraction differs from the 36 qualified flattened grounded-dummy notices"
    }
    feedback clear
    ext2sim labels on
    ext2sim

    load $SOURCE_TOP
    select top cell
    expand
    flatten $CLEAN_TOP
    load $CLEAN_TOP
    select top cell
    box 0.0um 0.0um 334.88um 225.76um
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
    set BASE [file join $WORKDIR output_${token}_base.spice]
    ext2spice -o $BASE ${TOP}.ext
    ext2spice extresist on
    set RC [file join $WORKDIR output_${token}_rc.spice]
    ext2spice -o $RC ${TOP}.ext
    set RES_EXT [file join $WORKDIR ${TOP}.res.ext]
    foreach required [list $BASE $RC $RES_EXT] {
        if {![file exists $required]} { error "missing $token output distributed-RC artifact: $required" }
    }
    puts "V3_FOUR_CHANNEL_OUTPUT_BASE_SPICE_${token}=$BASE"
    puts "V3_FOUR_CHANNEL_OUTPUT_RC_SPICE_${token}=$RC"
    puts "V3_FOUR_CHANNEL_OUTPUT_RES_EXT_${token}=$RES_EXT"
}
quit -noprompt
