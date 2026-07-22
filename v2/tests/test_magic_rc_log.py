import unittest

from v2.tools.check_magic_rc_log import audit_text


GOOD_LOG = """\
SUPPORT_RC_DRC_COUNT=0
SUPPORT_RC_EXTRACTION_FEEDBACK_COUNT=0
Total Nets: 10
Nets extracted: 8 (0.8)
Nets output: 8 (0.8)
exttospice finished.
exttospice finished.
SUPPORT_BASE_SPICE=/tmp/base.spice
SUPPORT_RC_SPICE=/tmp/rc.spice
SUPPORT_RES_EXT=/tmp/top.res.ext
"""


class MagicRcLogTests(unittest.TestCase):
    def test_good_log_passes(self) -> None:
        self.assertTrue(audit_text(GOOD_LOG)["passed"])

    def test_silent_node_error_fails_even_with_zero_feedback(self) -> None:
        report = audit_text(GOOD_LOG + "Error in extracting node foo\n")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["no_silent_magic_failures"])

    def test_missing_device_and_tcl_errors_fail(self) -> None:
        for line in (
            "Couldn't find device driving bar\n",
            'can\'t read "TOP": no such variable\n',
            'Error while reading cell "broken"\n',
            "Unexpected record type in input: Expected XY record but got ANGLE.\n",
            'Don\'t know how to read GDS-II:\nNothing in "cifinput" section of tech file.\n',
            'Using technology "minimum", version 0.0\n',
            'Error parsing "check.tcl": assembled top cell was not imported\n',
        ):
            with self.subTest(line=line):
                self.assertFalse(audit_text(GOOD_LOG + line)["passed"])

    def test_incomplete_statistics_fail(self) -> None:
        report = audit_text(GOOD_LOG.replace("Nets output: 8", "Nets output: 7"))
        self.assertFalse(report["checks"]["distributed_nets_emitted"])


if __name__ == "__main__":
    unittest.main()
