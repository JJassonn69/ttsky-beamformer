import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ControlPinAccessContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads(
            (ROOT / "build/v2/control_routing/control_pin_access_catalog.json").read_text()
        )
        cls.allocation = json.loads(
            (ROOT / "build/v2/control_routing/control_route_allocation.json").read_text()
        )
        cls.route_audit = json.loads(
            (ROOT / "build/v2/control_routing/openroad/route_audit.json").read_text()
        )

    def test_every_mapped_pin_has_one_orientation_transformed_access_record(self) -> None:
        records = self.catalog["records"]
        keys = [(item["instance"], item["pin"]) for item in records]
        self.assertEqual(self.catalog["status"], "pass")
        self.assertEqual(len(records), 719)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(item["selected_access"]["inside_inset_lef_port"]
                            for item in records))
        self.assertTrue(all(item["legal_access_rects"] for item in records))

    def test_all_213_service_endpoints_are_catalogued_and_finally_connected(self) -> None:
        service_endpoints = {
            (endpoint["instance"], endpoint["pin"])
            for route in self.allocation["nets"]
            if route["class"] == "service_tree"
            for endpoint in route["endpoints"]
            if endpoint["kind"] == "standard_cell_pin"
        }
        catalog_keys = {
            (item["instance"], item["pin"]) for item in self.catalog["records"]
        }
        self.assertEqual(len(service_endpoints), 213)
        self.assertTrue(service_endpoints <= catalog_keys)
        routed_service = {
            item["net"]: item for item in self.route_audit["nets"]
            if item["net"] in {
                route["net"] for route in self.allocation["nets"]
                if route["class"] == "service_tree"
            }
        }
        self.assertEqual(len(routed_service), 6)
        self.assertTrue(all(item["electrical_group_count"] == 1
                            for item in routed_service.values()))


if __name__ == "__main__":
    unittest.main()
