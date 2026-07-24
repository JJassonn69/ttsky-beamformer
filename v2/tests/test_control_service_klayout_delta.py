import unittest

from v2.tools.check_control_service_klayout_delta import canonical_value


class ControlServiceKlayoutDeltaTest(unittest.TestCase):
    def test_edge_pair_direction_and_pair_order_are_irrelevant(self) -> None:
        first = "edge-pair: (1,2;3,4)/(5,6;7,8)"
        second = "edge-pair: (7,8;5,6)/(3,4;1,2)"
        self.assertEqual(canonical_value(first), canonical_value(second))

    def test_polygon_rotation_and_direction_are_irrelevant(self) -> None:
        first = "polygon: (0,0;1,0;1,1;0,1)"
        second = "polygon: (1,1;1,0;0,0;0,1)"
        self.assertEqual(canonical_value(first), canonical_value(second))


if __name__ == "__main__":
    unittest.main()
