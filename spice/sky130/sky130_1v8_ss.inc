* Minimal slow-slow model closure for 1.8 V core MOSFETs.
.include "third_party/sky130_fd_pr/models/parameters/lod.spice"
.param sky130_fd_pr__nfet_01v8__dlc_rotweak=0
.param sky130_fd_pr__pfet_01v8__dlc_rotweak=0
.include "third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__ss.corner.spice"
.include "third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__mismatch.corner.spice"
.include "third_party/sky130_fd_pr/cells/pfet_01v8/sky130_fd_pr__pfet_01v8__ss.corner.spice"
.include "third_party/sky130_fd_pr/cells/pfet_01v8/sky130_fd_pr__pfet_01v8__mismatch.corner.spice"
