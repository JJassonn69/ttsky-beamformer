# Legacy two-channel layout flow

The files in this root directory reproduce the original 1x2 two-channel
prototype and are retained as historical engineering provenance. They do not
generate, extract, or sign off the active submission.

The active four-channel floorplan and constraints are under `v2/layout/`; its
authoritative physical-design record is `v2/spec/physical_design.md`. The root
submission wrapper is generated from the frozen V2 candidate by
`v2/tools/generate_submission_gds.py` and
`tools/generate_submission_lef.py`.
