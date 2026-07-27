# Generate endpoint-rooted distributed-RC views of the eight integrated
# selector-output/phase-tree paths.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v3 channel_selector_late_promotion v3_channel_selector_late_promotion.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_selector_late_promotion rc]
set SOURCE_TOP v3_channel_selector_late_promotion
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing integrated late-promotion selector/channel GDS" }

gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $SOURCE_TOP] < 0} {
    error "integrated selector/channel top was not imported"
}
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext $WORKDIR/*.nodes $WORKDIR/*.sim $WORKDIR/*.spice] {
    file delete -force $stale
}

# Absolute coordinates: the channel begins at (20,20) um and the selector at
# (20,143) um.  Rooting each view at the selector M2 output includes the new
# straight M2/M3/M4 join as well as the complete frozen analog phase tree.
set endpoints {
    {g1_lon 27.22 143.42 met2}
    {g1_lop 27.94 143.42 met2}
    {g2_lon 28.66 143.42 met2}
    {g2_lop 29.38 143.42 met2}
    {g4_lon 30.10 143.42 met2}
    {g4_lop 30.82 143.42 met2}
    {g8_lon 31.54 143.42 met2}
    {g8_lop 32.26 143.42 met2}
}
foreach endpoint $endpoints {
    lassign $endpoint token root_x root_y root_layer
    set TOP v3_channel_selector_late_promotion_rc_${token}
    set CLEAN_TOP ${TOP}_clean

    load $SOURCE_TOP
    select top cell
    expand
    flatten $TOP
    load $TOP
    select top cell
    box 15.0um -10.0um 45.0um 180.0um
    erase labels
    box ${root_x}um ${root_y}um ${root_x}um ${root_y}um
    label {res:drive@} FreeSans 0.10u -${root_layer}
    label {res:force@} FreeSans 0.10u -${root_layer}

    drc euclidean on
    drc style drc(full)
    drc check
    set drc_count [drc list count total]
    puts "V3_CHANNEL_SELECTOR_LATE_RC_DRC_COUNT_${token}=$drc_count"
    if {$drc_count != 0} { error "refusing $token integrated RCX with DRC errors" }

    extract unique notopports
    extract do local
    extract all
    set feedback_count [feedback count]
    puts "V3_CHANNEL_SELECTOR_LATE_RC_EXTRACTION_FEEDBACK_COUNT_${token}=$feedback_count"
    if {$feedback_count != 9} {
        feedback save [file join $WORKDIR extraction_feedback_${token}.txt]
        error "$token integrated RC extraction differs from the nine intentional grounded-dummy notices"
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
    box 15.0um -10.0um 45.0um 180.0um
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
        if {![file exists $required]} { error "missing $token integrated distributed-RC output: $required" }
    }
    puts "V3_CHANNEL_SELECTOR_LATE_BASE_SPICE_${token}=$BASE"
    puts "V3_CHANNEL_SELECTOR_LATE_RC_SPICE_${token}=$RC"
    puts "V3_CHANNEL_SELECTOR_LATE_RES_EXT_${token}=$RES_EXT"
}
quit -noprompt
