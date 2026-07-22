import tempfile
import unittest
from pathlib import Path

from v2.tools.generate_rc_force_attributes import collect_labels, generate


class RcForceAttributeTests(unittest.TestCase):
    def test_only_routed_signal_labels_are_forced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            route = root / "route.tcl"
            route.write_text(
                "box 1um 2um 1um 2um\n"
                "label {ch0_input} FreeSans 0.10u -met4\n"
                "box 3um 4um 3um 4um\n"
                "label {ch0_lop} FreeSans 0.10u -met3\n"
                "box 5um 6um 5um 6um\n"
                "label {sum_p} FreeSans 0.10u -met4\n",
                encoding="utf-8",
            )
            self.assertEqual(
                collect_labels([route]),
                [
                    ("ch0_input", "1", "2", "1", "2", "met4"),
                    ("ch0_lop", "3", "4", "3", "4", "met3"),
                    ("sum_p", "5", "6", "5", "6", "met4"),
                ],
            )
            output = root / "force.tcl"
            self.assertEqual(generate([route], output), 3)
            text = output.read_text(encoding="utf-8")
            self.assertIn("explicit RC drive point for ch0_input", text)
            self.assertIn("label {res:force@}", text)
            self.assertIn("label {res:drive@}", text)
            lop = text.split("explicit RC drive point for ch0_lop", 1)[1]
            lop = lop.split("# explicit RC drive point", 1)[0]
            self.assertNotIn("res:force@", lop)
            self.assertIn("res:drive@", lop)
            output_pad = text.split("explicit RC drive point for sum_p", 1)[1]
            self.assertIn("res:force@", output_pad)
            self.assertIn("res:drive@", output_pad)


if __name__ == "__main__":
    unittest.main()
