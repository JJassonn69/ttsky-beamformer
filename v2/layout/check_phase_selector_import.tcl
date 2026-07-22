# Import the minimal pinned standard-cell subset, place one repeated selector
# from generated DEF, and report flat placement DRC before any routing exists.

set PROJECT_ROOT [pwd]
set CELL_DIR [file join $PROJECT_ROOT third_party sky130_fd_sc_hd_cells]
set DEF_FILE [file join $PROJECT_ROOT build v2 phase_selector_layout phase_selector.def]
set OUT_DIR [file join $PROJECT_ROOT build v2 phase_selector_layout magic]
file mkdir $OUT_DIR

foreach cell {mux2_1 and2_1 buf_4 inv_1 tapvpwrvgnd_1} {
    lef read [file join $CELL_DIR sky130_fd_sc_hd__${cell}.lef]
}
foreach cell {mux2_1 and2_1 buf_4 inv_1 tapvpwrvgnd_1} {
    gds read [file join $CELL_DIR sky130_fd_sc_hd__${cell}.gds]
}

def read $DEF_FILE
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
puts "PHASE_SELECTOR_IMPORT_DRC_COUNT=[drc list count total]"
if {[drc list count total] != 0} {
    error "refusing phase-selector artifact with DRC errors"
}

cd $OUT_DIR
save v2_phase_selector_placement.mag
feedback clear
gds compress 0
gds write v2_phase_selector_placement.gds
set gds_feedback [feedback count]
puts "PHASE_SELECTOR_GDS_FEEDBACK_COUNT=$gds_feedback"
if {$gds_feedback != 0} {
    feedback save phase_selector_gds_feedback.txt
    error "refusing phase-selector artifact with $gds_feedback GDS writer problems"
}
quit -noprompt
