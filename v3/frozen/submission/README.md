# Frozen V3 submission candidate

This directory is the hash-bound internal-signoff bundle for
`tt_um_jjassonn69_beamformer`.

- GDS SHA-256:
  `824e38f94ce4fbff84d0c079dcb059d6944bca7569a0f657134c318f31553c14`
- PDK: SKY130A
- allocation: Tiny Tapeout 2x2, 334.88 um x 225.76 um
- supply: 1.8 V `VDPWR` / `VGND`; no `VAPWR`
- current state: internal signoff and official GitHub custom-GDS, viewer,
  precheck, and artifact-bound validation passed on this exact artifact

`gds_packaging.json` proves deterministic packaging and that removing only the
final non-electrical full-die project boundary reproduces the exact electrical
wrapper used for Magic extraction. `official_contract.json` mirrors the
official wrapper checks. `topology_audit.json` records extracted device and net
connectivity. `direct_precheck/` contains the pinned direct-GDS marker results.
`magic/` contains hierarchical and flat extraction evidence. `review/`
contains eight flattened visual-inspection views.
`github_attestation.json` records the completed official GitHub workflow and
job identifiers that attested this exact GDS hash.

The operator-facing circuit description, pin protocol, limits, startup
sequence, and evidence map are in `v3/docs/datasheet.md`.

Do not edit files in this directory manually. Regenerate from the authoritative
sources and rerun every affected gate. A release is valid only when the
canonical `gds/tt_um_jjassonn69_beamformer.gds`, this frozen GDS, and the
published GitHub artifact have the SHA-256 above.
