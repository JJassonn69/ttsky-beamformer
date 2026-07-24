# Beamformer V2 workspace

This directory contains the authoritative four-channel implementation,
validation, and datasheet. The repository-root submission metadata, wrapper
GDS/LEF, Verilog boundary, and CI now target this V2 design. Historical V1
models remain available only as explicitly named provenance.

The V2 branch starts from V1 release commit
`91749fe4298b00708b150c9e0df9752d59cc74fe`.

## Scope

- Four phase-coherent element channels.
- Four selectable DFT beam states using 0, 90, 180, and 270 degree weights.
- Four independent 4-bit equal-unit switched-tail gain trims,
  not as signal-path phase shifters.
- Manual phase override and per-channel enable for characterization.
- A six-analog-pin interface reserved for eventual TX/RX reuse.
- V2A signoff target: active four-channel receive beamformer.
- V2B research target: reciprocal or switched TX/RX operation, promoted only
  after its loading, loss, isolation, and package sensitivity pass simulation.

The architecture contract is in [spec/beamformer_v2.md](spec/beamformer_v2.md).
The first executable model is in [model/beamformer_v2.py](model/beamformer_v2.py).

## First model check

```sh
python3 -m unittest discover -s v2/tests -p 'test_*.py'
python3 v2/model/beamformer_v2.py summary
```

Current physical work is on the `v2-four-channel-beamformer` branch. The V2
candidate is deterministically packaged into the root Tiny Tapeout artifacts;
the packaging changes only the top-cell name and no geometry.

## Current physical checkpoint

- 194 mapped SKY130 HD control cells, 269 well taps, and qualified `fill_1`
  continuity cells on a deterministic placement.
- Route-aware legal mirroring of 19 residual global cells; 29.77% weighted
  HPWL improvement over naive row-major placement.
- Exact hierarchy-preserving powered GDS SHA-256
  `cf25e276fcb99a6c5e8559822ded5b4ec132e616a9a9583bbce3d425db7b6f81`.
- Full Magic DRC and import feedback both zero.
- All 206 physical control nets are owned by one OpenROAD detailed route.
  The audited result contains 7,557.34 um of wire and 1,478 vias, reaches only
  M4, has zero route cycles or unattached leaves, and uses M4 on only 13 nets.
- All 207 control nets have a frozen topology and track-capacity allocation.
  The one observation-only net, `mixers_blank`, has no physical consumer and
  is deliberately omitted rather than drawn as a floating stub.
- Exact final topology extraction verifies all 206 route labels, 790 final
  endpoints, 12 phase handoffs, four quadrature handoffs, 48 trim endpoint
  roles, 968/968 power/body pins, and all four analog resistor B/R1/R2
  terminal triplets, with no signal-to-power short.
- The exact final GDS is `v2_control_quadrature_routed`, SHA-256
  `1b76aba2cf2362071e248fdeb6532e22ab6a928f1b8ce9f5c35393381aa89741`.
  It is assembled from the hash-frozen user-routed source
  `950a98877295c3b4ca90e660a64c312035a62721fe8486dbe5ff6af07fa90c9c`
  plus four foundry `cap_var_lvt` VCM-to-ground bypass devices.
  It passes Magic full-chip DRC and extraction feedback with zero errors. The
  KLayout full-deck delta has 2,768 inherited source markers and 2,778 final
  markers. The only ten additions are classified `ct.2` markers inside the
  four foundry varactor PCells; nothing else is added, removed, or moved.
- Direct-GDS checks reject malformed cuts, unenclosed vias, via-only M3
  islands, MIM-clearance errors, narrow stubs, and abandoned transitions. All
  final mcon/via1/via2/via3 cuts have their exact legal 0.17/0.15/0.20/0.20 um
  dimensions.
- Full distributed-RC extraction contains 95,139 explicit resistors, 34,054
  capacitors, and 4,208 extracted devices, with 254/254 control, analog,
  supply, and output-pad nets
  covered. Magic's single classified `viali` message is an extresist meshing
  fallback; it is not used as a physical-rule waiver.
- The current-hash exact 20-case distributed-RC beam codebook is the final
  functional matrix and uses raw, unsubtracted output for acceptance. The
  four constructive responses span 23.49 to 24.16 mV RMS, with 0.244 dB
  spread and 61.05 dB worst raw rejection. The 60-seed open-PDK coefficient
  MOS-mismatch campaign passes every hard gate and 12 dB target; its worst
  rejection is 36.53 dB and its exact one-sided 95% zero-failure lower bound
  is 95.13%. The
  current distributed-RC cold start reaches
  1.10 V at 60.989 us and 1.17 V at 97.456 us, supporting a conservative
  120 us first-silicon enable delay. The current 64-case base extracted trim
  sweep supplies 2.342–2.344 dB span with a 0.115 dB minimum step.
- The V2 regression covers deterministic regeneration, direct-GDS rules,
  extracted topology, RC completeness, simulation contracts, and negative
  regressions. The exact executed count is recorded only after the final
  current-hash release run.

Key files:

- [detailed engineering datasheet](docs/datasheet.md)
- [physical-design record](spec/physical_design.md)
- [control signal allocation contract](layout/control_signal_plan.json)
- [final control-routing checkpoint](layout/control_routing_checkpoint.json)
- [powered GDS](../build/v2/control_power/direct/v2_four_channel_control_powered.gds)
- [final control-routing GDS](../build/v2/control_routing/direct/v2_control_quadrature_routed.gds)
- [exact-final routing overview](evidence/images/beamformer-v2-exact-final-overview.png)
- [exact-final varactor detail](evidence/images/beamformer-v2-exact-final-varactor-detail.png)
- [datasheet characterization figures and numeric data](evidence/datasheet_figures.json)
- [open the V2 branch GDS in the TinyTapeout viewer](https://gds-viewer.tinytapeout.com/?pdk=sky130A&model=https%3A%2F%2Fraw.githubusercontent.com%2FJJassonn69%2Fttsky-beamformer%2Fv2-four-channel-beamformer%2Fbuild%2Fv2%2Fcontrol_routing%2Fdirect%2Fv2_control_quadrature_routed.gds)

The V2 geometry now drives the root submission wrapper. The selected physical
root fix is 32 fixed equal tail-current units plus the 1/2/4/8 trim bank at
reset code 8. Placement, routing, DRC, topology, distributed RC, trim,
startup, load, linearity, clock, PVT endpoints, the complete beam matrix, and
modeled mismatch now bind to this exact GDS. Periodically switched mixer
noise, foundry-qualified yield,
package/board behavior, and measured beam patterns remain honest research-chip
residuals. The official TinyTapeout workflow is the final handoff gate. See
the hierarchical gates in [the pre-silicon plan](../docs/presilicon_plan.md).
