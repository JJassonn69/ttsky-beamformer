# Active V2 submission record

`template.lock` binds the current four-channel candidate, deterministic
Tiny Tapeout GDS wrapper, 2x2 LEF, metadata, Verilog boundary, distributed-RC
netlist, and nominal RC summary hashes.

The machine-readable electrical status is
`v2/evidence/latest_validation.json`. It deliberately records remaining gates
and does not claim fabrication readiness before the official Tiny Tapeout run.

The former two-channel signoff bundle is preserved under
`legacy/v1/submission/`; nothing in the active workflow reads that archive.
