# Frozen V3 four-channel shared-power integration

This directory is the immutable input to the V3 control and analog-input
integration stages. The authoritative top cell is
`v3_four_channel_power_integration`.

- GDS SHA-256: `edeab1f4e3f79dbe8dd318df6e3a503669a0a16be8e54ea0a0f1e53b9acc6ddf`
- flat SPICE SHA-256: `45d81eeb7644a59114544db4282afab6605b0aa8c75fe5f884de3c061fd9bfcc`
- Magic DRC markers: 0
- direct-GDS shuttle precheck markers: 0
- extracted devices: 1,315
- unified `VDPWR` terminal occurrences: 740
- unified `VGND` terminal occurrences: 1,360
- extracted `VDPWR`/`VGND` equivalences: 0
- supply domain: 1.8 V `VDPWR` only; `VAPWR` is unused

The west `VDPWR` spine deliberately stays on Metal 3 while crossing beneath
the Metal-4 `VGND` trunk. An earlier DRC-clean candidate used Metal 4 for both
routes and therefore shorted the rails in extraction. The manifest regression
test now rejects every same-layer overlap between newly added power and ground
routes, pins, and via landings; the exact flat extraction remains authoritative.

Do not edit this frozen GDS. Regenerate a derived top only from the hash-bound
stage input in `v3/CURRENT.json`.
