import json
import unittest
from pathlib import Path

from v2.tools.map_control_netlist import map_netlist, render_structural_verilog


ROOT = Path(__file__).resolve().parents[2]


class ControlNetlistMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = map_netlist(
            json.loads(
                (ROOT / "build/v2/control_synthesis/generic_netlist.json").read_text()
            ),
            "v2_physical_control_core",
            ROOT / "third_party/sky130_fd_sc_hd_cells",
        )

    def test_every_generic_leaf_maps_to_real_cells(self) -> None:
        self.assertEqual(self.report["counts"]["total_cells"], 194)
        self.assertEqual(
            self.report["counts"]["by_region"],
            {
                "global_control_core": 81,
                "phase_configuration_bank": 49,
                "trim_configuration_bank": 64,
            },
        )

    def test_active_and_shift_storage_stay_in_their_banks(self) -> None:
        counts = self.report["counts"]["by_role"]
        self.assertEqual(counts["phase_active_storage"], 8)
        self.assertEqual(counts["phase_shift_storage"], 8)
        self.assertEqual(counts["trim_active_storage"], 16)
        self.assertEqual(counts["trim_shift_storage"], 16)
        for cell in self.report["cells"]:
            if cell["role"].startswith("phase_"):
                self.assertEqual(cell["region"], "phase_configuration_bank")
            if cell["role"].startswith("trim_"):
                self.assertEqual(cell["region"], "trim_configuration_bank")

    def test_power_and_reset_mapping_are_explicit(self) -> None:
        for cell in self.report["cells"]:
            self.assertEqual(cell["pins"]["VGND"], "VGND")
            self.assertEqual(cell["pins"]["VPWR"], "VDPWR")
            if cell["short_cell"] == "dfrtp":
                self.assertIn("RESET_B", cell["pins"])
            if cell["short_cell"] == "dfstp":
                self.assertIn("SET_B", cell["pins"])

    def test_no_pseudo_or_unknown_cells_remain(self) -> None:
        allowed = set(self.report["library"])
        self.assertTrue(allowed)
        self.assertTrue(
            all(cell["short_cell"] in allowed for cell in self.report["cells"])
        )
        self.assertFalse(
            any(cell["cell"].startswith("$_") for cell in self.report["cells"])
        )

    def test_library_records_real_pin_access_geometry(self) -> None:
        for cell_name, cell in self.report["library"].items():
            self.assertAlmostEqual(cell["size_um"][0] / 0.46, round(cell["size_um"][0] / 0.46))
            self.assertAlmostEqual(cell["size_um"][1], 2.72)
            for pin_name, pin in cell["pins"].items():
                self.assertTrue(
                    pin["access_rects"], f"{cell_name}.{pin_name} has no LEF access"
                )
                for access in pin["access_rects"]:
                    self.assertIn("layer", access)
                    self.assertEqual(len(access["rect_um"]), 4)

    def test_shared_output_bits_are_explicit_aliases(self) -> None:
        aliases = self.report["port_aliases"]
        self.assertEqual(aliases["active_phase_codes[0]"], "phase_select0[0]")
        self.assertEqual(aliases["active_phase_codes[1]"], "phase_select1[0]")
        verilog = render_structural_verilog(self.report)
        self.assertIn(
            "assign active_phase_codes[0] = phase_select0[0];", verilog
        )

    def test_child_port_aliases_merge_into_one_physical_net(self) -> None:
        aliases = self.report["port_aliases"]
        self.assertEqual(aliases["phase_wave[1]"], "phase_wave[1]")
        state_consumers = [
            endpoint
            for endpoint in self.report["nets"]["phase_wave[1]"]
            if endpoint["instance"].startswith("core/")
        ]
        quadrature_drivers = [
            endpoint
            for endpoint in self.report["nets"]["phase_wave[1]"]
            if endpoint["instance"].startswith("quadrature_generator/")
            and endpoint["pin"] == "Q"
        ]
        self.assertTrue(state_consumers)
        self.assertEqual(len(quadrature_drivers), 1)

    def test_channel_decode_is_local_but_shared_logic_is_not(self) -> None:
        for channel in range(4):
            local = [
                cell
                for cell in self.report["cells"]
                if cell["role"] == f"channel{channel}_phase_decode"
            ]
            self.assertGreaterEqual(len(local), 4)
            self.assertTrue(
                all(cell["region"] == "phase_configuration_bank" for cell in local)
            )
        self.assertTrue(
            all(
                cell["region"] == "global_control_core"
                for cell in self.report["cells"]
                if cell["role"] == "quadrature_core"
            )
        )


if __name__ == "__main__":
    unittest.main()
