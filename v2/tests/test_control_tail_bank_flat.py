import unittest

from v2.tools.check_control_tail_bank_flat import audit, nfet_devices


def device(name: str, drain: str, gate: str, source: str) -> str:
    return (
        f"X{name} {drain} {gate} {source} VGND "
        "sky130_fd_pr__nfet_01v8 w=1.26 l=0.5\n"
    )


def valid_flat_view() -> str:
    lines: list[str] = []
    index = 0
    for channel in range(4):
        tail = f"ch{channel}_tail"
        for _ in range(32):
            lines.append(device(str(index), tail, "ch0_vbias", "VGND"))
            index += 1
        for weight in (1, 2, 4, 8):
            for _ in range(weight):
                lines.append(device(
                    str(index), tail, f"CH{channel}_TTRIM{weight}/G", "VGND"
                ))
                index += 1
    return "".join(lines)


class ControlTailBankFlatTests(unittest.TestCase):
    def test_exact_32_plus_binary_fingers_pass(self) -> None:
        report = audit(valid_flat_view())
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertEqual(report["verified_fixed_finger_count"], 128)
        self.assertEqual(report["verified_binary_trim_finger_count"], 60)
        for channel in report["channels"]:
            self.assertEqual(
                channel["trim_finger_counts"],
                {"1": 1, "2": 2, "4": 4, "8": 8},
            )

    def test_floating_outer_drain_is_rejected(self) -> None:
        text = valid_flat_view().replace(
            "ch0_tail CH0_TTRIM2/G VGND",
            "FLOATING_OUTER CH0_TTRIM2/G VGND",
            1,
        )
        report = audit(text)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(
            "trim weight 2 contains floating or miswired" in error
            for error in report["errors"]
        ))

    def test_drain_source_short_is_rejected(self) -> None:
        text = valid_flat_view().replace(
            "ch3_tail CH3_TTRIM8/G VGND",
            "ch3_tail CH3_TTRIM8/G ch3_tail",
            1,
        )
        report = audit(text)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any(
            "floating or miswired" in error for error in report["errors"]
        ))

    def test_flat_parser_ignores_non_target_models(self) -> None:
        text = device("0", "ch0_tail", "ch0_vbias", "VGND")
        text += "Xother a b c d unrelated_model l=0.5\n"
        self.assertEqual(len(nfet_devices(text)), 1)


if __name__ == "__main__":
    unittest.main()
