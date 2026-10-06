import unittest

from shapely.geometry import box

from geotest.tiling import analyze_hex_tiling


class HexTilingTests(unittest.TestCase):
    def test_regular_hex_tiling_covers_country_and_counts_intersections(self) -> None:
        country = box(-20, -10, 20, 10)

        result = analyze_hex_tiling(
            country,
            edge_length_km=10,
            offset_east_km=0,
            offset_north_km=0,
            rotation_degrees=0,
        )

        self.assertTrue(result.fully_covered)
        self.assertAlmostEqual(result.uncovered_area_km2, 0.0, places=6)
        self.assertGreater(len(result.cells), 0)
        self.assertTrue(
            all(0 < cell.coverage_ratio <= 1 for cell in result.cells)
        )
        self.assertAlmostEqual(result.cell_area_km2, 3 * 3**0.5 / 2 * 100)

    def test_grid_still_covers_country_after_offset_and_rotation(self) -> None:
        country = box(-20, -10, 20, 10)

        result = analyze_hex_tiling(
            country,
            edge_length_km=8,
            offset_east_km=4,
            offset_north_km=-3,
            rotation_degrees=27,
        )

        self.assertTrue(result.fully_covered)
        self.assertAlmostEqual(
            sum(cell.country_area_km2 for cell in result.cells),
            country.area,
            places=5,
        )

    def test_rejects_nonpositive_edge_length(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            analyze_hex_tiling(box(0, 0, 1, 1), edge_length_km=0)


if __name__ == "__main__":
    unittest.main()
