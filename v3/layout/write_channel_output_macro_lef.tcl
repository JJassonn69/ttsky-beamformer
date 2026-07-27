# Build an exact routing abstraction for the analog channel.  Only the 30
# differential unit outputs are exposed; all existing conductor geometry is
# retained as routing obstruction.
set PROJECT_ROOT [file normalize [pwd]]
set INPUT_GDS [file join $PROJECT_ROOT build v3 channel_input_bias_pilot v3_channel_input_bias_pilot.gds]
set WORKDIR [file join $PROJECT_ROOT build v3 channel_output_route]
set TOP v3_channel_input_bias_pilot
set MACRO ${TOP}_output_macro
file mkdir $WORKDIR
cd $WORKDIR
catch {cellname delete $TOP}
gds readonly false
gds rescale false
gds read $INPUT_GDS
load $TOP
select top cell
expand
# LEF obstruction generation must see exact flattened conductor polygons.
# Writing the hierarchical top directly makes Magic conservatively replace
# each child by its bounding box, which falsely blocks almost all M2--M4.
catch {cellname delete $MACRO}
flatten $MACRO
load $MACRO
select top cell
expand

set outputs {
    {u00_outp 22.32 104.23} {u00_outn 23.02 104.23}
    {u01_outp 27.52 104.23} {u01_outn 28.22 104.23}
    {u02_outp 32.72 104.23} {u02_outn 33.42 104.23}
    {u03_outp 22.32 88.23}  {u03_outn 23.02 88.23}
    {u04_outp 27.52 88.23}  {u04_outn 28.22 88.23}
    {u05_outp 32.72 88.23}  {u05_outn 33.42 88.23}
    {u06_outp 22.32 72.23}  {u06_outn 23.02 72.23}
    {u07_outp 27.52 72.23}  {u07_outn 28.22 72.23}
    {u08_outp 33.42 72.23}  {u08_outn 32.72 72.23}
    {u09_outp 23.02 56.23}  {u09_outn 22.32 56.23}
    {u10_outp 28.22 56.23}  {u10_outn 27.52 56.23}
    {u11_outp 33.42 56.23}  {u11_outn 32.72 56.23}
    {u12_outp 23.02 40.23}  {u12_outn 22.32 40.23}
    {u13_outp 28.22 40.23}  {u13_outn 27.52 40.23}
    {u14_outp 33.42 40.23}  {u14_outn 32.72 40.23}
}
foreach item $outputs {
    lassign $item name x y
    box [expr {$x - 0.20}]um [expr {$y - 0.20}]um [expr {$x + 0.20}]um [expr {$y + 0.20}]um
    label $name center metal3
    port make
    port class output
    port use signal
    port connections n s e w
}
save ${MACRO}.mag
lef write [file join $WORKDIR ${MACRO}.lef] -hide
quit -noprompt
