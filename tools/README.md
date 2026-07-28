# Tool routing

Active submission tools are:

- `v2/tools/` for four-channel generation, routing, extraction, simulation,
  and evidence checks;
- `tools/generate_submission_lef.py` for the 2x2 Tiny Tapeout LEF; and
- `tools/check_release_files.py` and `tools/check_documented_metrics.py` for
  current V2 release integrity.

Other root `tools/` scripts belong to the original two-channel development
flow and are retained only because its models/tests remain useful historical
regressions. They are not called by the active Makefile or GitHub workflow.
