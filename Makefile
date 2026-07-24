PYTHON ?= python3
IVERILOG ?= iverilog
BUILD_DIR := build
TOP := tt_um_jjassonn69_beamformer

.PHONY: test test-v2 test-submission datasheet-figures submission-gds submission-lef submission-artifacts v2-tail-screen v2-gate3 v2-gate4 v2-gate5 freeze-release-evidence release-check

# The unqualified targets operate on the active four-channel V2 submission.
test: test-v2

test-v2:
	$(PYTHON) -m unittest discover -s v2/tests -p 'test_*.py' -v

test-submission:
	$(PYTHON) -m unittest v2.tests.test_submission_artifacts -v
	mkdir -p $(BUILD_DIR)
	$(IVERILOG) -g2012 -s $(TOP) -o $(BUILD_DIR)/project.vvp src/project.v

datasheet-figures:
	$(PYTHON) v2/tools/generate_datasheet_figures.py

submission-gds:
	$(PYTHON) v2/tools/generate_submission_gds.py

submission-lef:
	$(PYTHON) tools/generate_submission_lef.py

submission-artifacts: submission-gds submission-lef test-submission

# Gate-1 architecture screen.  This is deliberately not part of release-check:
# it selects a candidate before physical regeneration and cannot sign off GDS.
v2-tail-screen:
	$(PYTHON) v2/tools/run_tail_headroom_screen.py

v2-gate3:
	$(PYTHON) v2/tools/check_gate3_candidate.py

v2-gate4: v2-gate3
	$(PYTHON) v2/tools/check_gate4_candidate.py

v2-gate5: v2-gate4
	$(PYTHON) v2/tools/check_gate5_candidate.py

freeze-release-evidence: v2-gate5 datasheet-figures
	$(PYTHON) v2/tools/freeze_release_evidence.py

release-check: submission-artifacts test-v2 v2-gate5
	$(PYTHON) v2/tools/check_latest_validation.py
