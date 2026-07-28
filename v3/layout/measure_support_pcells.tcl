# V3 physical Gate 3B: measure guarded 64 um / 1.00 um bias-reference
# folding candidates.  This creates a dimension catalogue only, not placement.

set WORKDIR [file normalize "build/v3/support_pcell_measurements"]
file mkdir $WORKDIR
cd $WORKDIR
file delete -force [file join $WORKDIR v3_support_pcell_measurement.mag]
catch {cellname delete v3_support_pcell_measurement}
load v3_support_pcell_measurement -silent

proc generate_reference {label x finger_width fingers} {
    box ${x}um 0um ${x}um 0um
    set generated [magic::gencell sky130::sky130_fd_pr__nfet_01v8 $label \
        w $finger_width l 1.00 nf $fingers m 1 guard 1 \
        conn_gates 1 full_metal 1 doports 1]
    puts "V3_SUPPORT_PCELL $label $generated"
}

# All candidates preserve exactly 64 um aggregate channel width.  The study
# selects folding from measured geometry; it does not change the schematic.
generate_reference XREF_4X16   0 16.0 4
generate_reference XREF_8X8   40  8.0 8
generate_reference XREF_16X4  80  4.0 16
generate_reference XREF_32X2 120  2.0 32

save v3_support_pcell_measurement.mag
writeall force
quit -noprompt
