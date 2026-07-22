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
    codebook_input_phases,
    deck_text,
    netlist_has_node,
    prepare_runtime,
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
        self.assertIn(".measure tran ch3_tail_max", text)
        self.assertIn("VINPK=0.005", text)

    def test_smoke_window_is_short_enough_for_iterative_signoff(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        self.assertIn(".tran 2n 4u 2u uic", text)
        self.assertIn(".option klu", text)
        self.assertIn("from=2u to=4u", text)
        self.assertNotIn("from=6u to=10u", text)
        self.assertIn(
            "VDD_SOURCE VDPWR 0 pulse(0 {VDD} 0 20n 20n 100u 200u)",
            text,
        )
        self.assertIn("VCLK R046 0 pulse(0 {VDD} 100n", text)

    def test_runtime_uses_isolated_large_sky130_configuration(self) -> None:
        for directive in (
            "set ngbehavior=hsa",
            "set skywaterpdk",
            "set ng_nomodcheck",
            "set num_threads=8",
            "option noinit",
            "option klu",
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
        self.assertIn(".tran 2n 16u 14u uic", text)
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
        self.assertIn(".tran 5n 48u 46u uic", text)
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
        self.assertIn("settled VCM is outside its nominal 1.2 V window", errors)

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
