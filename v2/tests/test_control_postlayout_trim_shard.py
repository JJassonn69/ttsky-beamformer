import unittest

from v2.tools.run_control_postlayout_trim_shard import parse_selection, shard_label


class ControlPostlayoutTrimShardTest(unittest.TestCase):
    def test_selection_accepts_sorted_unique_values_and_ranges(self) -> None:
        self.assertEqual(
            parse_selection("3,1-2,2", minimum=0, maximum=3),
            [1, 2, 3],
        )
        self.assertEqual(
            parse_selection("0-15", minimum=0, maximum=15),
            list(range(16)),
        )

    def test_selection_rejects_invalid_or_out_of_range_values(self) -> None:
        for value in ("", "2-1", "0,", "16"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_selection(value, minimum=0, maximum=15)

    def test_label_is_deterministic(self) -> None:
        self.assertEqual(
            shard_label([1, 2, 3], [0, 1, 2]),
            "channels_1-2-3_codes_0-1-2",
        )


if __name__ == "__main__":
    unittest.main()
