import unittest
import uncertainty


class AcvBandEdges(unittest.TestCase):
    def test_shared_frequency_edge_belongs_to_the_lower_row(self):
        s = uncertainty.load()
        at_edge = s.dmm('ACV', 1.0, 1.0, frequency=20.0)          # rows 10-20 Hz (0.06 %) and >20-40 Hz (0.024 %): 20 Hz is in the lower row
        above = s.dmm('ACV', 1.0, 1.0, frequency=20.5)
        self.assertGreater(at_edge, above)
        self.assertGreaterEqual(at_edge, 0.0006)


if __name__ == '__main__':
    unittest.main()
