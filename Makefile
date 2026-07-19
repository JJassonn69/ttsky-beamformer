PYTHON ?= python3
NGSPICE ?= ngspice
BUILD_DIR := build

.PHONY: verify test golden spice sky130-smoke transconductor mixer bias lo-buffer core passives pvt-quick pvt layout-template layout-scripts layout-place layout-route layout-extract layout-sim layout-pvt-quick layout-pvt layout-signoff release-check

verify: test golden spice sky130-smoke transconductor mixer bias lo-buffer core passives

test:
	$(PYTHON) -m unittest discover -s tests -v

golden:
	mkdir -p $(BUILD_DIR)
	$(PYTHON) model/beamformer.py summary --output $(BUILD_DIR)/golden_summary.json
	$(PYTHON) model/beamformer.py sweep --output $(BUILD_DIR)/golden_phase_sweep.csv

spice:
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/ideal_ngspice.log spice/ideal/beamformer_ideal.spice
	$(PYTHON) tools/check_ideal_spice.py $(BUILD_DIR)/ideal_ngspice.log

sky130-smoke:
	test -f third_party/sky130_fd_pr/models/parameters/lod.spice
	test -f third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__tt.corner.spice
	test -f third_party/sky130_fd_pr/cells/nfet_01v8/sky130_fd_pr__nfet_01v8__mismatch.corner.spice
	test -f third_party/sky130_fd_pr/cells/pfet_01v8/sky130_fd_pr__pfet_01v8__tt.corner.spice
	test -f third_party/sky130_fd_pr/cells/pfet_01v8/sky130_fd_pr__pfet_01v8__mismatch.corner.spice
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/sky130_smoke.log spice/sky130/model_smoke.spice
	$(PYTHON) tools/check_sky130_smoke.py $(BUILD_DIR)/sky130_smoke.log

transconductor: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/transconductor.log spice/sky130/transconductor.spice
	$(PYTHON) tools/check_transconductor.py $(BUILD_DIR)/transconductor.log

mixer: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/two_channel_mixer.log spice/sky130/two_channel_mixer.spice
	$(PYTHON) tools/check_two_channel_mixer.py $(BUILD_DIR)/two_channel_mixer.log

bias: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/bias_mirror.log spice/sky130/bias_mirror.spice
	$(PYTHON) tools/check_bias_mirror.py $(BUILD_DIR)/bias_mirror.log

lo-buffer: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/lo_buffer.log spice/sky130/lo_buffer.spice
	$(PYTHON) tools/check_lo_buffer.py $(BUILD_DIR)/lo_buffer.log

core: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/beamformer_core.log spice/sky130/beamformer_core.spice
	$(PYTHON) tools/check_beamformer_core.py $(BUILD_DIR)/beamformer_core.log

passives: sky130-smoke
	mkdir -p $(BUILD_DIR)
	$(NGSPICE) -b -o $(BUILD_DIR)/passive_smoke.log spice/sky130/passive_smoke.spice
	$(PYTHON) tools/check_passives.py $(BUILD_DIR)/passive_smoke.log

pvt-quick: sky130-smoke
	$(PYTHON) tools/run_core_pvt.py --ngspice $(NGSPICE)

pvt: sky130-smoke
	$(PYTHON) tools/run_core_pvt.py --full --ngspice $(NGSPICE)

layout-template:
	$(PYTHON) tools/fetch_tt_template.py

layout-scripts:
	$(PYTHON) tools/generate_layout_scripts.py

layout-place: layout-template layout-scripts
	tools/run_magic_layout.sh build/layout/place.tcl

layout-route:
	$(PYTHON) tools/generate_route_script.py
	$(PYTHON) tools/check_generated_routes.py build/layout/route.tcl
	tools/run_magic_layout.sh build/layout/route.tcl

layout-extract:
	tools/run_magic_layout.sh layout/extract.tcl
	$(PYTHON) tools/check_extracted_layout.py build/layout/extracted.spice build/layout/buffered/tt_um_jjassonn69_beamformer.ext

layout-sim:
	$(PYTHON) tools/run_extracted_sim.py --ngspice $(NGSPICE)
	$(PYTHON) tools/check_beamformer_core.py $(BUILD_DIR)/extracted_core.log

layout-pvt-quick:
	$(PYTHON) tools/run_extracted_pvt.py --ngspice $(NGSPICE)

layout-pvt:
	$(PYTHON) tools/run_extracted_pvt.py --full --ngspice $(NGSPICE)

layout-signoff:
	tools/run_magic_layout.sh layout/signoff.tcl
	$(PYTHON) tools/generate_submission_lef.py

release-check:
	$(PYTHON) tools/check_release_files.py
	iverilog -g2012 -s tt_um_jjassonn69_beamformer -o $(BUILD_DIR)/project.vvp src/project.v
