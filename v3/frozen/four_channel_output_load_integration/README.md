# Frozen V3 four-channel output-load integration

This directory is the immutable input to the next V3 top-level routing stage.
The authoritative top cell is `v3_four_channel_output_load_integration`.

- GDS SHA-256: `16c045e05f05168008237a1179d9b89af0c5cbc1120ef431507e42f1786f52f9`
- flat SPICE SHA-256: `a35db9f1c1345b1644b454875d930439fbd393f1ffdd987c63bf5347358be0e8`
- Magic DRC markers: 0
- direct-GDS shuttle precheck markers: 0
- extracted devices: 1,315
- differential output route mean-resistance mismatch: 0.3334%
- effective output-capacitance mismatch: 0.1852%
- estimated output time-constant mismatch: 0.1652%

The P-side 4.20 um MIM is intentional compensation for the otherwise 12.61%
extracted differential capacitance mismatch. It is connected between the P
output and ground; it is not a load bypass or a routing artifact.

The three VDPWR namespaces are intentionally still separate. Shared power,
static control, and four analog-input pad escapes belong to the next gate.
Do not edit this frozen GDS. Regenerate a derived top from the hash-bound
source named in `v3/CURRENT.json`.
