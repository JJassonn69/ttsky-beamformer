import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_smoke import (
    CONTROL_NODES,
    PHASE_NODES,
    RC_PHASE_LEAF_NODES,
    RC_PHASE_ROOT_NODES,
    SPICE_INIT,
    analyze,
    clock_source,
    codebook_input_phases,
    deck_text,
    netlist_has_node,
    prepare_runtime,
    serial_trim_sources,
    validate_extracted_netlist,
)


class ControlPostlayoutSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gds = ROOT / "build/v2/control_routing/direct/v2_control_quadrature_routed.gds"
        cls.base = ROOT / "build/v2/control_routing/final_rc/control_final_base.spice"
        cls.rc = ROOT / "build/v2/control_routing/final_rc/control_final_rc.spice"

    def test_both_frozen_views_have_exact_supported_model_and_node_closure(self) -> None:
        for path in (self.base, self.rc):
            validate_extracted_netlist(path.read_text(errors="replace"))

    def test_generated_deck_binds_netlist_and_gds_hashes(self) -> None:
        netlist_hash = hashlib.sha256(self.base.read_bytes()).hexdigest()
        gds_hash = hashlib.sha256(self.gds.read_bytes()).hexdigest()
        text = deck_text(self.base.relative_to(ROOT), netlist_hash, gds_hash)
        self.assertIn(f"extracted_netlist_sha256={netlist_hash}", text)
        self.assertIn(f"final_gds_sha256={gds_hash}", text)
        self.assertIn('.include "v2/spice/extracted_model_aliases.inc"', text)
        self.assertIn('.include "build/v2/control_routing/final_rc/control_final_base.spice"', text)
        self.assertIn(".measure tran vcm_avg avg v(ch0_vcm)", text)
        self.assertIn("BTONEI tone_i 0 v=v(differential)*cos(2*pi*FOUT*time)", text)
        self.assertIn("BTONEQ tone_q 0 v=v(differential)*sin(2*pi*FOUT*time)", text)
        self.assertIn(".measure tran output_tone_rms param=", text)
        self.assertIn(".measure tran core_lo_rms param=", text)
        self.assertIn(".measure tran core_cm_lo_rms param=", text)
        self.assertIn(".measure tran vcm_rf_rms param=", text)
        self.assertIn(".measure tran vcm_lo_rms param=", text)
        self.assertIn(".measure tran ch0_gm_p_min", text)
        self.assertIn(
            "BCH0GM_PVDS ch0_gm_p_vds_probe 0 v=v(ch0_gm_p)-v(ch0_tail)", text
        )
        self.assertIn(
            ".measure tran ch0_gm_p_vds_min min v(ch0_gm_p_vds_probe)", text
        )
        self.assertIn(
            ".measure tran ch3_gm_n_vds_max max v(ch3_gm_n_vds_probe)", text
        )
        self.assertIn(".measure tran ch3_tail_max", text)
        self.assertIn("VINPK=0.005", text)
        self.assertIn("FIN=5meg FOUT=1meg FLO=4meg", text)

    def test_rf_frequency_control_keeps_rated_lo_and_tracks_difference_tone(self) -> None:
        text = deck_text(
            Path("view.spice"), "a", "b",
            input_frequency_mhz=4.5,
            analysis_start_us=2.0,
            analysis_stop_us=4.0,
        )
        self.assertIn("FIN=4.5meg FOUT=0.5meg FLO=4meg", text)
        self.assertIn("VCLK R046 0 pulse(0 {VDD} 100n", text)
        with self.assertRaises(ValueError):
            deck_text(Path("view.spice"), "a", "b", input_frequency_mhz=4.0)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "a", "b",
                input_frequency_mhz=4.5,
                analysis_start_us=2.0,
                analysis_stop_us=3.0,
            )

    def test_clock_duty_and_jitter_stresses_are_reproducible(self) -> None:
        self.assertIn(
            "pulse(0 {VDD} 100n 200p 200p 31.05n 62.5n)",
            clock_source(CONTROL_NODES["clk"]),
        )
        duty = clock_source(CONTROL_NODES["clk"], duty_percent=40.0)
        self.assertIn("24.8n 62.5n", duty)
        jitter = clock_source(
            CONTROL_NODES["clk"], jitter_ps=1000.0, stop_us=1.0
        )
        self.assertIn("VCLK R046 0 pwl(0 0 99n 0 99.2n {VDD}", jitter)
        self.assertIn("163.5n 0 163.7n {VDD}", jitter)
        self.assertEqual(
            jitter,
            clock_source(CONTROL_NODES["clk"], jitter_ps=1000.0, stop_us=1.0),
        )
        with self.assertRaises(ValueError):
            clock_source(CONTROL_NODES["clk"], duty_percent=70.0)
        with self.assertRaises(ValueError):
            clock_source(CONTROL_NODES["clk"], jitter_ps=2500.0)

    def test_pvt_controls_select_matching_model_supply_and_temperature(self) -> None:
        text = deck_text(
            self.base.relative_to(ROOT),
            "a" * 64,
            "b" * 64,
            process_corner="ss",
            supply_voltage_v=1.62,
            temperature_c=85,
        )
        self.assertIn(".temp 85", text)
        self.assertIn("sky130_1v8_ss.inc", text)
        self.assertIn("pfet_01v8_hvt__ss.corner.spice", text)
        self.assertIn(".param VDD=1.62", text)

    def test_pvt_controls_reject_unsupported_ranges(self) -> None:
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", process_corner="unknown")
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", supply_voltage_v=2.5)
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", temperature_c=150)
        with self.assertRaises(ValueError):
            deck_text(Path("x"), "a", "b", passive_corner="unknown")

    def test_passive_corner_selects_matching_resistor_and_capacitor_models(self) -> None:
        text = deck_text(Path("x"), "a", "b", passive_corner="hl")
        self.assertIn("res_high__cap_low.spice", text)
        self.assertIn("res_high__cap_low__lin.spice", text)
        self.assertNotIn("res_typical__cap_typical.spice", text)

    def test_nondefault_trim_uses_one_lsb_first_serial_commit(self) -> None:
        sources = "\n".join(serial_trim_sources((1, 2, 4, 8)))
        self.assertIn("VCFGCLK R030 0 pwl", sources)
        self.assertIn("VCFGDATA R032 0 pwl(0 {VDD}", sources)
        self.assertIn("VCFGLATCH R033 0 pwl", sources)
        self.assertIn("825n", sources)
        clock = serial_trim_sources((1, 2, 4, 8))[0]
        self.assertEqual(clock.count("n {VDD}"), 50)
        self.assertIn("830n {VDD}", clock)
        self.assertTrue(clock.endswith("839.8n {VDD} 840n 0)"))
        text = deck_text(
            Path("view.spice"), "a", "b", trim_codes=(1, 2, 4, 8)
        )
        self.assertNotIn("VCFGCLK R030 0 0", text)
        self.assertIn(".measure tran trim0_min min v(R008)", text)
        self.assertIn(".measure tran trim15_max max v(R014)", text)
        self.assertIn(".measure tran apply_config_max max v(R024) from=0 to=2u", text)
        self.assertIn(".measure tran serial_trim_max max v(R158) from=0 to=2u", text)
        self.assertIn(".tran 2n 4u 0", text)

    def test_default_trim_stays_at_reset_code_without_serial_activity(self) -> None:
        text = deck_text(Path("view.spice"), "a", "b")
        self.assertIn("VCFGCLK R030 0 0", text)
        self.assertIn("VCFGDATA R032 0 0", text)
        self.assertIn("VCFGLATCH R033 0 0", text)
        with self.assertRaises(ValueError):
            deck_text(Path("view.spice"), "a", "b", trim_codes=(0, 1, 2, 16))

    def test_smoke_window_is_short_enough_for_iterative_signoff(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        self.assertIn(".tran 2n 4u 0 uic", text)
        self.assertIn(".option klu", text)
        self.assertIn("from=2u to=4u", text)
        self.assertNotIn("from=6u to=10u", text)
        self.assertIn(
            "VDD_SOURCE VDPWR 0 pulse(0 {VDD} 0 20n 20n 100u 200u)",
            text,
        )
        self.assertIn("VCLK R046 0 pulse(0 {VDD} 100n", text)
        self.assertIn(
            ".measure tran vcm_valid_first when v(ch0_vcm)=1.1 rise=1",
            text,
        )
        self.assertIn(
            ".measure tran vcm_valid_settled when v(ch0_vcm)=1.1 rise=last",
            text,
        )

    def test_runtime_uses_isolated_large_sky130_configuration(self) -> None:
        for directive in (
            "set ngbehavior=hsa",
            "set skywaterpdk",
            "set ng_nomodcheck",
            "set num_threads=8",
            "option noinit",
            "option klu",
            "option rshunt=1e15",
        ):
            self.assertIn(directive, SPICE_INIT)
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime = prepare_runtime(Path(temporary_directory))
            self.assertEqual(
                (runtime / ".spiceinit").read_text(encoding="utf-8"),
                SPICE_INIT,
            )
            for name in ("build", "spice", "third_party", "v2"):
                link = runtime / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (ROOT / name).resolve())

    def test_runtime_repairs_only_a_stale_generated_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            work = Path(temporary_directory)
            runtime = prepare_runtime(work)
            stale = runtime / "build"
            stale.unlink()
            stale.symlink_to(work / "obsolete-checkout", target_is_directory=True)
            repaired = prepare_runtime(work)
            self.assertEqual(
                (repaired / "build").resolve(),
                (ROOT / "build").resolve(),
            )

    def test_runtime_does_not_replace_a_real_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            work = Path(temporary_directory)
            (work / "runtime" / "build").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "blocks required link"):
                prepare_runtime(work)

    def test_special_nfet_alias_population_is_frozen_in_both_views(self) -> None:
        token = "sky130_fd_pr__special_nfet_01v8"
        self.assertEqual(self.base.read_text(errors="replace").count(token), 298)
        self.assertEqual(self.rc.read_text(errors="replace").count(token), 298)

    def test_rc_deck_measures_every_selector_leaf_against_its_root(self) -> None:
        text = deck_text(
            Path("view.spice"), "netlist-hash", "gds-hash",
            distributed_rc=True,
        )
        rc_netlist = self.rc.read_text(errors="replace")
        for phase, leaves in enumerate(RC_PHASE_LEAF_NODES):
            self.assertIn(RC_PHASE_ROOT_NODES[phase], rc_netlist)
            for channel, leaf in enumerate(leaves):
                self.assertIn(leaf, rc_netlist)
                self.assertIn(f"v({leaf})", text)
                self.assertIn(f"phase{phase}_ch{channel}_delay", text)
        self.assertIn("ROUTP ch0_out_p.n0 outp_pad 500", text)
        self.assertIn("ROUTN ch0_out_n.n0 outn_pad 500", text)
        self.assertIn("ch0_out_p.n0", rc_netlist)
        self.assertIn("ch0_out_n.n0", rc_netlist)

    def test_smoke_drives_only_real_extracted_external_control_nodes(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        for node in CONTROL_NODES.values():
            self.assertIn(f" {node} 0 ", text)
        for node in PHASE_NODES:
            self.assertIn(f"v({node})", text)
        self.assertIn("ch0_input", text)
        self.assertIn("ch3_input", text)
        self.assertIn("ch0_out_p", text)
        self.assertIn("ch0_out_n", text)

    def test_extracted_node_validation_does_not_accept_substrings(self) -> None:
        self.assertTrue(netlist_has_node("X1 ch0_phase_0_leaf 0 model\n", "ch0_phase_0_leaf"))
        self.assertTrue(netlist_has_node("R1 ch0_phase_0_leaf.t0 n1 1\n", "ch0_phase_0_leaf"))
        self.assertFalse(netlist_has_node("X1 ch0_phase_0_leaf 0 model\n", "phase_0"))

    def test_default_case_is_beam_zero_with_all_four_channels_enabled(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        self.assertIn("VBEAM0 R025 0 0", text)
        self.assertIn("VBEAM1 R026 0 0", text)
        for index, node in enumerate(("R038", "R039", "R040", "R041")):
            self.assertIn(f"BCH{index} {node} 0 v=v(VDPWR)", text)

    def test_single_channel_mask_disables_the_other_three_channels(self) -> None:
        text = deck_text(
            Path("view.spice"), "netlist-hash", "gds-hash",
            channel_mask=0x4,
        )
        self.assertIn("VCH0 R038 0 0", text)
        self.assertIn("VCH1 R039 0 0", text)
        self.assertIn("BCH2 R040 0 v=v(VDPWR)", text)
        self.assertIn("VCH3 R041 0 0", text)

    def test_zero_rf_input_preserves_the_enabled_mixer_testbench(self) -> None:
        text = deck_text(
            Path("view.spice"), "netlist-hash", "gds-hash",
            input_peak_v=0.0,
        )
        self.assertIn("VINPK=0", text)
        for index, node in enumerate(("R038", "R039", "R040", "R041")):
            self.assertIn(f"BCH{index} {node} 0 v=v(VDPWR)", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                input_peak_v=-1e-3,
            )

    def test_operating_point_startup_uses_dc_vdd_and_drops_uic(self) -> None:
        text = deck_text(
            Path("view.spice"), "netlist-hash", "gds-hash",
            operating_point_startup=True,
        )
        self.assertIn("VDD_SOURCE VDPWR 0 {VDD}", text)
        self.assertIn(".tran 2n 4u 2u\n", text)
        self.assertNotIn(".tran 2n 4u 2u uic", text)

    def test_late_window_supports_physical_startup_settling_checks(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            analysis_start_us=14.0,
            analysis_stop_us=16.0,
        )
        self.assertIn(".tran 2n 16u 0 uic", text)
        self.assertIn("from=14u to=16u", text)
        self.assertIn("rise=1 td=14u", text)

    def test_analysis_window_is_coherent_and_increasing(self) -> None:
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                analysis_start_us=4.0, analysis_stop_us=2.0,
            )
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                analysis_start_us=2.0, analysis_stop_us=4.5,
            )

    def test_coarser_startup_step_remains_explicit_and_bounded(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            analysis_start_us=46.0,
            analysis_stop_us=48.0,
            transient_step_ns=5.0,
        )
        self.assertIn(".tran 5n 48u 0 uic", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"),
                "netlist-hash",
                "gds-hash",
                transient_step_ns=20.0,
            )

    def test_staged_enable_keeps_mixers_blanked_during_bias_charge(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            analysis_start_us=46.0,
            analysis_stop_us=48.0,
            transient_step_ns=5.0,
            enable_delay_us=40.0,
        )
        self.assertIn("VENA R067 0 pulse(0 {VDD} 40u", text)
        self.assertNotIn("BENA R067 0 v=v(VDPWR)", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"),
                "netlist-hash",
                "gds-hash",
                analysis_start_us=46.0,
                analysis_stop_us=48.0,
                enable_delay_us=50.0,
            )

    def test_output_shunt_models_lower_impedance_summing_load(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            output_shunt_ohms=5000.0,
        )
        self.assertIn("RSHUNTP ch0_out_p VDPWR 5000", text)
        self.assertIn("RSHUNTN ch0_out_n VDPWR 5000", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"),
                "netlist-hash",
                "gds-hash",
                output_shunt_ohms=0.0,
            )

    def test_vbias_bypass_experiment_is_explicit_and_measured(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            vbias_bypass_pf=10.0,
        )
        self.assertIn("CBIAS_BYPASS ch0_vbias 0 10p", text)
        self.assertIn(".measure tran vbias_min", text)
        self.assertIn(".measure tran vbias_max", text)
        self.assertIn(".measure tran vcm_min", text)
        self.assertIn(".measure tran vcm_max", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"),
                "netlist-hash",
                "gds-hash",
                vbias_bypass_pf=-1.0,
            )

    def test_output_damping_experiment_is_symmetric_at_core_outputs(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            output_damping_pf=10.0,
        )
        self.assertIn("CDAMPP ch0_out_p VDPWR 10p", text)
        self.assertIn("CDAMPN ch0_out_n VDPWR 10p", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                output_damping_pf=0.0,
            )

    def test_vcm_bypass_experiment_targets_shared_reference(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            vcm_bypass_pf=10.0,
        )
        self.assertIn("CVCM_BYPASS ch0_vcm 0 10p", text)
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                vcm_bypass_pf=-1.0,
            )

    def test_vcm_varactor_experiment_uses_foundry_model_and_shared_reference(self) -> None:
        model = Path("build/v2/varactor_study/cap_var_lvt.model.spice")
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            vcm_varactor_model=model,
            vcm_varactor_w_um=25.0,
            vcm_varactor_l_um=25.0,
            vcm_varactor_m=2,
        )
        self.assertIn(f'.include "{model.as_posix()}"', text)
        self.assertIn(
            "XVCM_VAR ch0_vcm 0 0 sky130_fd_pr__cap_var_lvt w=25 l=25 vm=2",
            text,
        )
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                vcm_bypass_pf=5.0,
                vcm_varactor_model=model,
            )
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                vcm_varactor_model=model,
                vcm_varactor_w_um=0.0,
            )
        with self.assertRaises(ValueError):
            deck_text(
                Path("view.spice"), "netlist-hash", "gds-hash",
                vcm_varactor_model=model,
                vcm_varactor_m=0,
            )

    def test_physical_varactor_model_closure_does_not_add_a_duplicate_device(self) -> None:
        model = Path("v2/spice/sky130_fd_pr__cap_var_lvt.model.spice")
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            extracted_varactor_model=model,
        )
        self.assertIn(f'.include "{model.as_posix()}"', text)
        self.assertNotIn("XVCM_VAR ch0_vcm", text)

    def test_varactor_models_are_numerically_safe_and_linearization_is_explicit(self) -> None:
        nonlinear = (
            ROOT / "v2/spice/sky130_fd_pr__cap_var_lvt.model.spice"
        ).read_text(encoding="utf-8")
        active_model = "\n".join(
            line for line in nonlinear.splitlines()
            if not line.lstrip().startswith("*")
        )
        self.assertNotIn("log(cosh(", active_model)
        self.assertIn("log(1+exp(-2*abs(", active_model)

        linearized = (
            ROOT / "v2/spice/sky130_fd_pr__cap_var_lvt.linearized_1p2v.spice"
        ).read_text(encoding="utf-8")
        self.assertIn("2.604860136214599p", linearized)
        self.assertIn("1097.313345683077", linearized)
        self.assertIn("used only for distributed-RC convergence checks", linearized)

    def test_rc_output_damping_uses_extracted_output_endpoints(self) -> None:
        text = deck_text(
            Path("view.spice"),
            "netlist-hash",
            "gds-hash",
            distributed_rc=True,
            output_damping_pf=5.0,
        )
        self.assertIn("CDAMPP ch0_out_p.n0 VDPWR 5p", text)
        self.assertIn("CDAMPN ch0_out_n.n0 VDPWR 5p", text)

    def test_four_ideal_incident_beams_match_the_dft_codebook(self) -> None:
        self.assertEqual(codebook_input_phases(0), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(codebook_input_phases(1), (0.0, 90.0, 180.0, 270.0))
        self.assertEqual(codebook_input_phases(2), (0.0, 180.0, 0.0, 180.0))
        self.assertEqual(codebook_input_phases(3), (0.0, 270.0, 180.0, 90.0))
        with self.assertRaises(ValueError):
            codebook_input_phases(4)

    def test_nonzero_beam_and_incident_phases_reach_the_deck(self) -> None:
        text = deck_text(
            Path("view.spice"), "netlist-hash", "gds-hash",
            beam=3,
            input_phases_deg=codebook_input_phases(3),
        )
        self.assertIn("VBEAM0 R025 0 {VDD}", text)
        self.assertIn("VBEAM1 R026 0 {VDD}", text)
        self.assertIn("VIN1 source1 0 sin(0 {VINPK} {FIN} 0 0 270)", text)
        self.assertIn("VIN2 source2 0 sin(0 {VINPK} {FIN} 0 0 180)", text)

    def test_uic_smoke_rejects_rail_stuck_vcm_but_allows_rc_startup(self) -> None:
        values = {
            "output_rms": 8e-4,
            "output_avg": 0.0,
            "output_tone_rms": 5e-4,
            "tone_i_avg": 2e-4,
            "tone_q_avg": 3e-4,
            "common_mode_avg": 1.79,
            "vcm_avg": 0.5,
            "supply_avg": -155e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.8
            values[f"phase{index}_period"] = 250e-9
        _, errors = analyze(values)
        self.assertEqual(errors, [])
        values["vcm_avg"] = 0.0
        _, errors = analyze(values)
        self.assertIn("VCM appears stuck at a supply rail during startup", errors)

    def test_off_beam_case_may_reach_an_ideal_null(self) -> None:
        values = {
            "output_rms": 0.0,
            "output_avg": 0.0,
            "output_tone_rms": 0.0,
            "tone_i_avg": 0.0,
            "tone_q_avg": 0.0,
            "common_mode_avg": 1.79,
            "vcm_avg": 0.5,
            "supply_avg": -155e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.8
            values[f"phase{index}_period"] = 250e-9
        _, errors = analyze(values, require_output=False)
        self.assertEqual(errors, [])

    def test_operating_point_analysis_enforces_settled_bias_windows(self) -> None:
        values = {
            "output_rms": 15e-3,
            "output_avg": 0.0,
            "output_tone_rms": 14e-3,
            "tone_i_avg": 9e-3,
            "tone_q_avg": 4e-3,
            "common_mode_avg": 0.985,
            "vcm_avg": 1.199,
            "supply_avg": -695e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.8
            values[f"phase{index}_period"] = 250e-9
        analysis, errors = analyze(
            values, settled_startup=True, full_channel_operation=True
        )
        self.assertEqual(errors, [])
        self.assertAlmostEqual(analysis["estimated_power_w"], 1.251e-3)
        values["vcm_avg"] = 0.5
        _, errors = analyze(
            values, settled_startup=True, full_channel_operation=True
        )
        self.assertIn(
            "settled VCM is outside its supply-scaled 0.60..0.73 VDD window",
            errors,
        )

    def test_runner_requires_every_time_aligned_headroom_probe(self) -> None:
        values = {
            "output_rms": 15e-3,
            "output_avg": 0.0,
            "output_tone_rms": 14e-3,
            "tone_i_avg": 9e-3,
            "tone_q_avg": 4e-3,
            "common_mode_avg": 0.985,
            "vcm_avg": 1.199,
            "supply_avg": -695e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.8
            values[f"phase{index}_period"] = 250e-9
        _, errors = analyze(values, require_headroom_probes=True)
        self.assertTrue(any("ch0_gm_n_vds_max" in error for error in errors))
        for channel in range(4):
            for branch in ("gm_p", "gm_n"):
                values[f"ch{channel}_{branch}_vds_min"] = 0.08
                values[f"ch{channel}_{branch}_vds_max"] = 0.4
        analysis, errors = analyze(values, require_headroom_probes=True)
        self.assertEqual(errors, [])
        self.assertEqual(
            analysis["minimum_time_aligned_gm_drain_to_tail_v"], 0.08
        )

    def test_settled_vcm_window_scales_at_low_supply_corner(self) -> None:
        values = {
            "output_rms": 15e-3,
            "output_avg": 0.0,
            "output_tone_rms": 14e-3,
            "tone_i_avg": 9e-3,
            "tone_q_avg": 4e-3,
            "common_mode_avg": 1.001,
            "vcm_avg": 1.079,
            "supply_avg": -527e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.62
            values[f"phase{index}_period"] = 250e-9
        _, errors = analyze(
            values, settled_startup=True, full_channel_operation=True,
            supply_voltage_v=1.62,
        )
        self.assertEqual(errors, [])

    def test_partial_channel_diagnostic_allows_higher_output_common_mode(self) -> None:
        values = {
            "output_rms": 1e-3,
            "output_avg": 0.0,
            "output_tone_rms": 1e-3,
            "tone_i_avg": 0.5e-3,
            "tone_q_avg": 0.5e-3,
            "common_mode_avg": 1.59,
            "vcm_avg": 1.199,
            "supply_avg": -277e-6,
        }
        for index in range(4):
            values[f"phase{index}_min"] = 0.0
            values[f"phase{index}_max"] = 1.8
            values[f"phase{index}_period"] = 250e-9
        _, errors = analyze(
            values, settled_startup=True, full_channel_operation=False
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
