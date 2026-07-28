import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMATIC = ROOT / "spice/sky130/beamformer_core.spice"
MANIFEST = ROOT / "layout/circuit.json"


class VcmManifestConsistencyTests(unittest.TestCase):
    def test_vcm_ratio_and_input_bias_match_schematic_and_layout(self) -> None:
        schematic = SCHEMATIC.read_text(encoding="utf-8")
        lengths = {
            name: float(length)
            for name, length in re.findall(
                r"^X(RVCMT|RVCMB|RIN1|RIN2)\b.*\bl=([0-9.]+)\s*$",
                schematic,
                re.MULTILINE,
            )
        }
        self.assertEqual(set(lengths), {"RVCMT", "RVCMB", "RIN1", "RIN2"})

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        physical = {
            str(device["name"]).removeprefix("X"): float(device["l"])
            for device in manifest["devices"]
            if device["name"] in {"XRVCMT", "XRVCMB", "XRIN1", "XRIN2"}
        }
        self.assertEqual(lengths, physical)
        self.assertAlmostEqual(lengths["RVCMT"] + lengths["RVCMB"], 141.0)
        self.assertAlmostEqual(lengths["RVCMB"] / lengths["RVCMT"], 2.0)
        self.assertEqual(lengths["RIN1"], lengths["RIN2"])


if __name__ == "__main__":
    unittest.main()
