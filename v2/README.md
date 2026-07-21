# Beamformer V2 workspace

This directory contains the four-channel V2 work. The inherited V1 source,
layout, GDS, evidence, and datasheet remain unchanged at the repository root.

The V2 branch starts from V1 release commit
`91749fe4298b00708b150c9e0df9752d59cc74fe`.

## Initial scope

- Four phase-coherent element channels.
- Four selectable DFT beam states using 0, 90, 180, and 270 degree weights.
- Four independent 4-bit R-2R gain trims used as static calibration controls,
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

No V2 geometry or circuit is allowed to replace the inherited V1 release
artifacts until the V2 architecture, golden model, and block-level SPICE gates
are complete.
