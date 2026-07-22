import unittest

from v2.tools.check_critical_extraction import (
    expected_local_trim_nodes,
    expected_nodes,
    expected_output_load_nodes,
    expected_phase_selector_nodes,
    expected_support_nodes,
    logical_lines,
    top_instances,
)


class CriticalExtractionTests(unittest.TestCase):
    def test_continuation_lines_are_collapsed(self) -> None:
        self.assertEqual(
            logical_lines("XU A B\n+ C model\n"),
            ["XU A B C model"],
        )

    def test_only_top_instances_are_returned(self) -> None:
        text = """
.subckt child A B
XINNER A B device
.ends
.subckt v2_four_channel_critical_routed
XTOP n1 n2 child
+ ignored_continuation model
.ends
"""
        self.assertEqual(
            top_instances(text),
            {"XTOP": ["n1", "n2", "child", "ignored_continuation"]},
        )

    def test_missing_top_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing .subckt"):
            top_instances(".subckt other A\n.ends\n")

    def test_trim_switch_terminals_remain_distinct(self) -> None:
        expected = expected_local_trim_nodes(2)
        self.assertEqual(
            expected["XCH2_TSW2_ON"],
            ["CH2_TTRIM4/G", "ch2_vbias", "CH2_TINV2/A", "VGND"],
        )
        self.assertEqual(
            expected["XCH2_TSW2_OFF"],
            ["CH2_TTRIM4/G", "VGND", "CH2_TINV2/Y", "VGND"],
        )
        self.assertEqual(len(expected), 19)

    def test_phase_selector_keeps_complementary_second_stage_inputs(self) -> None:
        expected = expected_phase_selector_nodes(1)
        self.assertEqual(
            expected["XCH1_PMUX_P"][-3:],
            ["CH1_PMUX_B/X", "ch1_phase_sel1", "CH1_PMUX_A/X"],
        )
        self.assertEqual(
            expected["XCH1_PMUX_N"][-3:],
            ["CH1_PMUX_A/X", "ch1_phase_sel1", "CH1_PMUX_B/X"],
        )
        self.assertEqual(expected["XCH1_PAND_P"][3], "ch1_phase_enable")
        self.assertEqual(expected["XCH1_PAND_N"][3], "ch1_phase_enable")
        for mux in ("PMUX_A", "PMUX_B", "PMUX_P", "PMUX_N"):
            nodes = expected[f"XCH1_{mux}"]
            self.assertNotEqual(nodes[1], nodes[6], f"{mux} VPWR is shorted to S")
        self.assertEqual(len(expected), 6)

    def test_global_tree_joins_only_corresponding_phase_inputs(self) -> None:
        expected = expected_phase_selector_nodes(3, global_phase_tree=True)
        self.assertEqual(expected["XCH3_PMUX_A"][-3:], [
            "ch0_phase_90_leaf", "ch3_phase_sel0", "ch0_phase_0_leaf",
        ])
        self.assertEqual(expected["XCH3_PMUX_B"][-3:], [
            "ch0_phase_270_leaf", "ch3_phase_sel0", "ch0_phase_180_leaf",
        ])

    def test_output_tree_joins_all_collectors_by_polarity(self) -> None:
        expected = expected_nodes(3, "VGND", output_summing=True)
        self.assertEqual(expected["XCH3_SW1_A"][1], "ch0_out_p")
        self.assertEqual(expected["XCH3_SW2_A"][1], "ch0_out_n")
        self.assertEqual(expected["XCH3_SW4_B"][4], "ch0_out_p")
        self.assertEqual(expected["XCH3_SW3_B"][4], "ch0_out_n")

    def test_output_load_r2_terminals_reach_shared_collectors(self) -> None:
        self.assertEqual(expected_output_load_nodes(), {
            "XLOAD_P": ["VGND", "LOAD_P/R1", "ch0_out_p"],
            "XLOAD_N": ["VGND", "LOAD_N/R1", "ch0_out_n"],
        })

    def test_support_network_joins_vcm_and_vbias_without_premature_vdd(self) -> None:
        support = expected_support_nodes()
        self.assertEqual(support["XRVCM_BOTTOM"], ["VGND", "ch0_vcm", "VGND"])
        self.assertEqual(
            support["XRVCM_TOP"], ["VGND", "RVCM_TOP/R1", "ch0_vcm"]
        )
        self.assertEqual(support["XCVCM"], ["VGND", "ch0_vcm", "VGND"])
        for index in range(4):
            self.assertEqual(
                support[f"XCVCM_VAR{index}"],
                ["ch0_vcm", "VGND", "VGND"],
            )
        self.assertEqual(support["XRBIAS"], ["VGND", "RBIAS/R1", "ch0_vbias"])
        for name in ("XBIAS_DIODE_A", "XBIAS_DIODE_B"):
            self.assertEqual(
                [support[name][index] for index in (1, 2, 4, 6, 8, 10)],
                ["ch0_vbias"] * 6,
            )
            self.assertEqual(
                [support[name][index] for index in (0, 3, 5, 7, 9, 11)],
                ["VGND"] * 6,
            )

    def test_shared_support_retargets_all_channel_analog_references(self) -> None:
        channel = expected_nodes(3, "VGND", output_summing=True, shared_vcm=True)
        trim = expected_local_trim_nodes(3, shared_vbias=True)
        self.assertEqual(channel["XCH3_RINPUT"][1], "ch0_vcm")
        self.assertEqual(channel["XCH3_GM_REF_A"][2], "ch0_vcm")
        self.assertEqual(trim["XCH3_TSW2_ON"][1], "ch0_vbias")


if __name__ == "__main__":
    unittest.main()
