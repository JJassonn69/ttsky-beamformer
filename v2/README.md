# Beamformer V2 workspace

This directory contains the four-channel V2 work. The inherited V1 source,
layout, GDS, evidence, and datasheet remain unchanged at the repository root.

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

V2 remains isolated from the inherited V1 release artifacts.  Current physical
work is on the `v2-four-channel-beamformer` branch.

## Current physical checkpoint

- 194 mapped SKY130 HD control cells, 269 well taps, and qualified `fill_1`
  continuity cells on a deterministic placement.
- Route-aware legal mirroring of 19 residual global cells; 29.77% weighted
  HPWL improvement over naive row-major placement.
- Exact hierarchy-preserving powered GDS SHA-256
  `cf25e276fcb99a6c5e8559822ded5b4ec132e616a9a9583bbce3d425db7b6f81`.
- Full Magic DRC and import feedback both zero.
- All 206 physical control nets are owned by one OpenROAD detailed route.
  The audited result contains 7,552.55 um of wire and 1,466 vias, reaches only
  M4, has zero route cycles or unattached leaves, and uses M4 on only 13 nets.
- All 207 control nets have a frozen topology and track-capacity allocation.
  The one observation-only net, `mixers_blank`, has no physical consumer and
  is deliberately omitted rather than drawn as a floating stub.
- Exact final topology extraction verifies all 206 route labels, 790 final
  endpoints, 12 phase handoffs, four quadrature handoffs, 48 trim endpoint
  roles, 968/968 power/body pins, and all four analog resistor B/R1/R2
  terminal triplets, with no signal-to-power short.
- The exact final GDS is `v2_control_quadrature_routed`, SHA-256
  `d9c9aae5771af815833668374924baee23f60a51747c7966e2517dcb6f6a6130`.
  It passes Magic full-chip DRC and extraction feedback with zero errors. The
  KLayout full-deck delta has 2,776 inherited markers in both source and
  candidate, with zero added and zero removed.
- Direct-GDS checks reject malformed cuts, unenclosed vias, via-only M3
  islands, MIM-clearance errors, narrow stubs, and abandoned transitions. All
  final mcon/via1/via2/via3 cuts have their exact legal 0.17/0.15/0.20/0.20 um
  dimensions.
- Full distributed-RC extraction contains 91,671 explicit resistors, 34,316
  capacitors, and 4,244 devices, with 254/254 control, analog, supply, and output-pad nets
  covered. Magic's single classified `viali` message is an extresist meshing
  fallback; it is not used as a physical-rule waiver.
- The complete local regression contains 168 V2 tests, eight shared
  direct-GDS rule tests, and 20 shared routing-constraint tests, all passing.

Key files:

- [detailed engineering datasheet](docs/datasheet.md)
- [physical-design record](spec/physical_design.md)
- [control signal allocation contract](layout/control_signal_plan.json)
- [final control-routing checkpoint](layout/control_routing_checkpoint.json)
- [powered GDS](../build/v2/control_power/direct/v2_four_channel_control_powered.gds)
- [final control-routing GDS](../build/v2/control_routing/direct/v2_control_quadrature_routed.gds)
- [final routing overview](../build/v2/control_routing/review/beamformer-v2-control-final-overview.png)
- [final top-detail view](../build/v2/control_routing/review/beamformer-v2-control-final-top-detail.png)
- [final reviewed trim-route view](../build/v2/control_routing/review/beamformer-v2-control-final-trim-detail.png)
- [final phase/quadrature-handoff view](../build/v2/control_routing/review/beamformer-v2-control-final-handoff-detail.png)
- [final output-load power detail](../build/v2/control_routing/review/beamformer-v2-control-final-load-power-detail.png)

This freezes the production control-routing checkpoint, not the full V2 chip.
No V2 geometry replaces the V1 release until the remaining analog/top-level
integration, post-layout analog and phase-code simulations, independent
signoff where available, and the official TinyTapeout workflow have passed.
