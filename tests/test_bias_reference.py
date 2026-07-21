import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMATIC = ROOT / "spice/sky130/beamformer_core.spice"
MANIFEST = ROOT / "layout/circuit.json"


class BiasReferenceConsistencyTests(unittest.TestCase):
    def test_bias_halves_are_parallel_diodes_on_two_distinct_nets(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        devices = {
            device["name"]: device
            for device in manifest["devices"]
            if device["name"] in {"XBIASA", "XBIASB"}
        }
        self.assertEqual(set(devices), {"XBIASA", "XBIASB"})
        for device in devices.values():
            self.assertEqual(device["kind"], "nmos")
            self.assertEqual(device["nets"], {
                "D": "vbias", "G": "vbias", "S": "VGND", "B": "VGND"
            })
            self.assertNotEqual(device["nets"]["D"], device["nets"]["S"])
            self.assertEqual(device["total_w"], 16.0)
            self.assertEqual(device["l"], 0.50)
            self.assertEqual(device["nf"], 9)

        schematic = SCHEMATIC.read_text(encoding="utf-8")
        instances = re.findall(
            r"^X(BIASA|BIASB)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
            r"sky130_fd_pr__nfet_01v8\s+w=([0-9.]+)\s+l=([0-9.]+)$",
            schematic,
            re.MULTILINE,
        )
        self.assertEqual(len(instances), 2)
        for _, drain, gate, source, body, width, length in instances:
            self.assertEqual((drain, gate, source, body),
                             ("vbias", "vbias", "vss", "vss"))
            self.assertNotEqual(drain, source)
            self.assertEqual(float(width), 16.0)
            self.assertEqual(float(length), 0.50)


if __name__ == "__main__":
    unittest.main()
