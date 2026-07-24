import unittest

from v2.tools.fetch_control_cells import ASSETS


class ControlCellAssetTests(unittest.TestCase):
    def test_minimal_control_library_is_pinned(self) -> None:
        self.assertEqual(
            set(ASSETS),
            {"and2b", "dfrtp", "dfstp", "fill", "nand2", "nor2", "or2", "or2b", "xor2"},
        )
        for cell, formats in ASSETS.items():
            expected = {"gds", "lef"} if cell == "fill" else {"gds", "lef", "spice"}
            self.assertEqual(set(formats), expected)
            for digest in formats.values():
                self.assertRegex(digest, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
