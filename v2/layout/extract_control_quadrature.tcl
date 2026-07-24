# Extract topology from the exact assembled quadrature-routed GDS.
set PROJECT_ROOT [pwd]
set INPUT_GDS [file join $PROJECT_ROOT build v2 control_routing direct v2_control_quadrature_routed.gds]
set WORKDIR [file join $PROJECT_ROOT build v2 control_routing quadrature_extraction]
set TOP v2_control_quadrature_routed
file mkdir $WORKDIR
if {![file exists $INPUT_GDS]} { error "missing exact quadrature-routed GDS" }
gds readonly yes
gds read $INPUT_GDS
if {[lsearch -exact [cellname list all] $TOP] < 0} { error "quadrature-routed top was not imported" }
cd $WORKDIR
foreach stale [glob -nocomplain $WORKDIR/*.ext] { file delete -force $stale }
load $TOP
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
set count [drc list count total]
puts "CONTROL_QUADRATURE_EXTRACTION_DRC_COUNT=$count"
if {$count != 0} { error "quadrature topology extraction has DRC errors" }
extract do local
extract all
set feedback_count [feedback count]
puts "CONTROL_QUADRATURE_EXTRACTION_FEEDBACK_COUNT=$feedback_count"
if {$feedback_count != 0} { error "quadrature extraction produced feedback" }
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
