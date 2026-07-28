import tempfile
import unittest
from pathlib import Path

from tools.check_distributed_rc import rc_details, resistor_node_aliases
from v2.tools.check_support_rc import audit, required_routed_nets


class SupportRcTests(unittest.TestCase):
    def test_required_nets_cover_shared_analog_and_all_channel_routes(self) -> None:
        nets = required_routed_nets()
        self.assertEqual(len(nets), 45)
        for net in ("VGND", "ch0_vcm", "ch0_vbias", "ch0_out_p", "ch0_out_n"):
            self.assertIn(net, nets)
        for channel in range(4):
            for suffix in (
                "input", "tail", "gm_p", "gm_n", "lop", "lon",
                "phase_sel0", "phase_sel1", "phase_enable",
            ):
                self.assertIn(f"ch{channel}_{suffix}", nets)
        for phase in ("0", "90", "180", "270"):
            self.assertIn(f"ch0_phase_{phase}_leaf", nets)

    def test_split_and_hierarchical_nodes_anchor_manifest_nets(self) -> None:
        self.assertEqual(resistor_node_aliases("ch0_out_p.n19"), {"ch0_out_p"})
        self.assertEqual(
            resistor_node_aliases("CH0_PBUF_N.VGND.t2"),
            {"CH0_PBUF_N.VGND", "VGND"},
        )
        details = rc_details(
            {
                "R": [
                    ["R1", "ch0_out_p.n0", "ch0_out_p.t0", "1"],
                    ["R2", "CH0_BUF.VGND.n0", "CH0_BUF.VGND.t0", "1"],
                ],
                "C": [],
                "X": [],
            },
            {"ch0_out_p", "VGND"},
        )
        self.assertEqual(details["uncovered_manifest_nets"], [])

    def test_attribute_pseudo_node_is_rejected(self) -> None:
        details = rc_details(
            {
                "R": [["R1", "ch0_vcm.n0", "res:drive@", "1"]],
                "C": [],
                "X": [],
            },
            {"ch0_vcm"},
        )
        self.assertEqual(details["attribute_like_resistor_nodes"], ["res:drive@"])

    def test_small_ext2spice_record_reduction_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.spice"
            rc = root / "rc.spice"
            ext = root / "top.ext"
            res_ext = root / "top.res.ext"
            base.write_text("X0 a b c d model\nC0 a b 1f\n", encoding="utf-8")
            # This fixture only checks the record-ratio policy; other audit
            # gates intentionally remain false for the miniature network.
            rc.write_text(
                "X0 a b c d model\nC0 a b 1f\nC1 a b 1f\n"
                + "".join(f"R{i} ch0_vcm.n{i} ch0_vcm.n{i + 1} 1\n" for i in range(97)),
                encoding="utf-8",
            )
            ext.write_text("timestamp 0\n", encoding="utf-8")
            res_ext.write_text(
                "".join(f"rnode n{i} 0 0 0 0 0\n" for i in range(100))
                + "".join(f"resist n{i} n{i + 1} 1\n" for i in range(100)),
                encoding="utf-8",
            )
            report = audit(base, rc, res_ext)
            self.assertTrue(report["checks"]["explicit_resistors_emitted"])
            self.assertAlmostEqual(
                report["annotation"]["spice_to_annotation_ratio"], 0.97
            )


if __name__ == "__main__":
    unittest.main()
