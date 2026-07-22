import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2/tools"))

from run_control_postlayout_smoke import (
    CONTROL_NODES,
    RC_PHASE_LEAF_NODES,
    RC_PHASE_ROOT_NODES,
    deck_text,
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

    def test_smoke_window_is_short_enough_for_iterative_signoff(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        self.assertIn(".tran 2n 4u 2u", text)
        self.assertIn("from=2u to=4u", text)
        self.assertNotIn("from=6u to=10u", text)

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

    def test_smoke_drives_only_real_extracted_external_control_nodes(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        for node in CONTROL_NODES.values():
            self.assertIn(f" {node} 0 ", text)
        for node in ("phase_0", "phase_90", "phase_180", "phase_270"):
            self.assertIn(f"v({node})", text)
        self.assertIn("ch0_input", text)
        self.assertIn("ch3_input", text)
        self.assertIn("ch0_out_p", text)
        self.assertIn("ch0_out_n", text)

    def test_default_case_is_beam_zero_with_all_four_channels_enabled(self) -> None:
        text = deck_text(Path("view.spice"), "netlist-hash", "gds-hash")
        self.assertIn("VBEAM0 R025 0 0", text)
        self.assertIn("VBEAM1 R026 0 0", text)
        for index, node in enumerate(("R038", "R039", "R040", "R041")):
            self.assertIn(f"VCH{index} {node} 0 {{VDD}}", text)


if __name__ == "__main__":
    unittest.main()
