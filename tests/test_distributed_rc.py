import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.check_distributed_rc import audit


class DistributedRcAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.base = root / "base.spice"
        self.rc = root / "rc.spice"
        self.res_ext = root / "top.res.ext"
        self.sim_rc = root / "sim.spice"
        self.top_ext = root / "top.ext"
        self.base.write_text("X0 a b model\nC0 a 0 1f\n", encoding="utf-8")
        self.rc.write_text(
            "X0 a.n0 b model\n"
            "C0 a.n0 0 1f\nC1 a 0 1f\n"
            "R0 a a.n0 1.0\nR1 b b.n0 2.0\nR2 a.n0 b.n0 3.0\n",
            encoding="utf-8",
        )
        self.top_ext.write_text("timestamp reference\n", encoding="utf-8")
        self.sim_rc.write_text(
            "X0 a b model\nC0 a 0 1f\nC1 b 0 1f\n"
            "R0 a b 1.0\nR1 b b.n0 2.0\n",
            encoding="utf-8",
        )
        self.res_ext.write_text(
            'rnode "a" 0 0 0 0 0\n'
            'rnode "a.n0" 0 0 0 0 0\n'
            'resist "a" "a.n0" 1000\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_accepts_explicit_distributed_network(self) -> None:
        with patch("tools.check_distributed_rc.manifest_nets", return_value={"a", "b"}):
            report = audit(self.base, self.rc, self.res_ext)
        self.assertTrue(report["passed"], json.dumps(report, indent=2))

    def test_rejects_capacitance_only_copy(self) -> None:
        with patch("tools.check_distributed_rc.manifest_nets", return_value={"a", "b"}):
            report = audit(self.base, self.base, self.res_ext)
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["explicit_resistors_emitted"])

    def test_rejects_stale_resistance_annotation(self) -> None:
        ext_time = self.top_ext.stat().st_mtime
        os.utime(self.res_ext, (ext_time - 1.0, ext_time - 1.0))
        with patch("tools.check_distributed_rc.manifest_nets", return_value={"a", "b"}):
            report = audit(self.base, self.rc, self.res_ext)
        self.assertFalse(report["checks"]["top_resistance_annotation_is_fresh"])

    def test_rejects_unanchored_resistor_component(self) -> None:
        self.rc.write_text(
            self.rc.read_text(encoding="utf-8") + "R3 floating floating.n0 4.0\n",
            encoding="utf-8",
        )
        with patch("tools.check_distributed_rc.manifest_nets", return_value={"a", "b"}):
            report = audit(self.base, self.rc, self.res_ext)
        self.assertFalse(report["passed"])
        self.assertFalse(
            report["checks"]["all_resistor_components_manifest_anchored"]
        )

    def test_accepts_separately_reduced_simulation_view(self) -> None:
        with patch("tools.check_distributed_rc.manifest_nets", return_value={"a", "b"}):
            report = audit(
                self.base, self.rc, self.res_ext, self.sim_rc, self.res_ext
            )
        self.assertTrue(report["passed"], json.dumps(report, indent=2))
        self.assertTrue(report["checks"]["simulation_network_reduced"])


if __name__ == "__main__":
    unittest.main()
