* Model closure for device names emitted only by flattened Magic extraction.
*
* SKY130's ngspice model bundle has no subcircuit named
* sky130_fd_pr__special_nfet_01v8.  Magic uses that name for ordinary 1.8 V
* NMOS polygons whose shared source/drain geometry cannot be merged into its
* usual extraction form.  Preserve every extracted W/L and junction parameter
* while delegating the electrical model to the foundry nfet_01v8 primitive.
.subckt sky130_fd_pr__special_nfet_01v8 d g s b
+ w=1 l=0.15 ad=0 as=0 pd=0 ps=0
XDEVICE d g s b sky130_fd_pr__nfet_01v8
+ w={w} l={l} ad={ad} as={as} pd={pd} ps={ps}
.ends sky130_fd_pr__special_nfet_01v8
