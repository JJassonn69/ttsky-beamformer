import json
import unittest
from pathlib import Path


V2_ROOT = Path(__file__).resolve().parents[1]


class PortCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads(
            (V2_ROOT / "layout" / "port_catalog.json").read_text()
        )

    def test_catalog_is_complete_for_production_components(self) -> None:
        self.assertEqual(self.catalog["status"], "pass", self.catalog["errors"])
        analog = self.catalog["analog_pcells"]
        for name in (
            "gm_nfet_guarded",
            "mixer_nfet_guarded",
            "bias_diode_nfet_guarded",
            "trim_main_third_nfet_shared_guard",
            "trim_bit8_nfet_shared_guard",
            "trim_switch_nfet_shared_guard",
            "input_bias_resistor_guarded",
            "output_load_resistor_guarded",
            "vcm_mim_capacitor",
            "vcm_varactor_lvt",
        ):
            self.assertIn(name, analog)
            self.assertTrue(analog[name]["ports"])

        bias = analog["bias_diode_nfet_guarded"]["ports"]
        self.assertEqual(len(bias["G"]), 9)
        self.assertEqual(len(bias["D"]), 5)
        self.assertEqual(len(bias["S"]), 5)

    def test_even_finger_tail_banks_include_the_real_outer_drain_contact(self) -> None:
        analog = self.catalog["analog_pcells"]
        expected = {
            "trim_main_third_nfet_shared_guard": (7, 6, "D12_physical_outer_contact"),
            "trim_bit8_nfet_shared_guard": (5, 4, "D8_physical_outer_contact"),
            "trim_bit4_nfet_shared_guard": (3, 2, "D4_physical_outer_contact"),
            "trim_bit2_nfet_shared_guard": (2, 1, "D2_physical_outer_contact"),
        }
        for name, (drains, sources, outer_label) in expected.items():
            ports = analog[name]["ports"]
            self.assertEqual(len(ports["D"]), drains, name)
            self.assertEqual(len(ports["S"]), sources, name)
            outer = ports["D"][-1]
            self.assertEqual(outer["label"], outer_label, name)
            self.assertIn("real symmetric outer ndiffc", outer["access_basis"])

    def test_phase_cells_expose_signal_and_power_ports(self) -> None:
        cells = self.catalog["standard_cells"]
        self.assertTrue({"A0", "A1", "S", "X", "VGND", "VPWR"}.issubset(
            cells["sc_hd_mux2_1"]["ports"]
        ))
        self.assertTrue({"A", "X", "VGND", "VPWR"}.issubset(
            cells["sc_hd_buf_4"]["ports"]
        ))

    def test_passive_ends_are_not_collapsed(self) -> None:
        analog = self.catalog["analog_pcells"]
        self.assertTrue({"R1", "R2", "B"}.issubset(
            analog["input_bias_resistor_guarded"]["ports"]
        ))
        self.assertTrue({"C1", "C2"}.issubset(
            analog["vcm_mim_capacitor"]["ports"]
        ))
        self.assertEqual(
            set(analog["vcm_varactor_lvt"]["ports"]),
            {"B", "D", "G", "S"},
        )


if __name__ == "__main__":
    unittest.main()
