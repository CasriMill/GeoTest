import unittest
from math import cos, radians, sin, sqrt

from geotest.hexgrid import (
    GridFit,
    _cells_cover_country,
    _linspace,
    _layout_cells,
    _quality,
    _score_cells,
    _translation_bounds,
    _transform_hexagons,
    fit_hexagon_and_seven_children,
    render_hex_grid_svg,
    render_third_level_svg,
)
from shapely.geometry import Polygon


BOUNDARY_RINGS = [
    (
        "outer",
        [
            (12.0, 50.0),
            (14.0, 51.0),
            (16.0, 50.0),
            (15.0, 48.0),
            (13.0, 48.0),
            (12.0, 50.0),
        ],
    )
]


def local_projection(point: tuple[float, float]) -> tuple[float, float]:
    center_lon = 14.0
    center_lat = 49.5
    return (
        (point[0] - center_lon) * cos(radians(center_lat)),
        point[1] - center_lat,
    )


def contains(hexagon, point) -> bool:
    vertices = [local_projection(vertex) for vertex in hexagon]
    point_x, point_y = local_projection(point)
    center_x = sum(x for x, _ in vertices) / len(vertices)
    center_y = sum(y for _, y in vertices) / len(vertices)
    for index, (x, y) in enumerate(vertices):
        next_x, next_y = vertices[(index + 1) % len(vertices)]
        edge_x, edge_y = next_x - x, next_y - y
        center_side = edge_x * (center_y - y) - edge_y * (center_x - x)
        point_side = edge_x * (point_y - y) - edge_y * (point_x - x)
        if center_side * point_side < -1e-8:
            return False
    return True


class HexGridTests(unittest.TestCase):
    def test_fits_one_parent_around_country_and_seven_children_inside(self) -> None:
        parent, children = fit_hexagon_and_seven_children(BOUNDARY_RINGS)

        self.assertEqual(len(parent), 6)
        self.assertEqual(len(children), 7)
        for _, ring in BOUNDARY_RINGS:
            for point in ring:
                self.assertTrue(contains(parent, point))
        for child in children:
            for vertex in child:
                self.assertTrue(contains(parent, vertex))

    def test_render_includes_parent_and_seven_child_outlines(self) -> None:
        svg = render_hex_grid_svg(BOUNDARY_RINGS)

        self.assertEqual(svg.count('stroke-width="2"'), 8)
        self.assertIn('stroke="#c62828"', svg)
        self.assertIn('stroke="#1565c0"', svg)
        self.assertIn("first hex grid level", svg)

    def test_third_level_layout_has_49_children_and_six_merged_cells(self) -> None:
        parent, second_level, third_level, crossing_cells = _layout_cells(
            (0.0, 0.0), 3.0, 0.0
        )

        self.assertEqual(len(parent), 6)
        self.assertEqual(len(second_level), 7)
        self.assertEqual(len(third_level), 49)
        self.assertEqual(len(crossing_cells), 6)

    def test_coverage_check_rejects_country_outside_grid(self) -> None:
        _, _, children, crossing_cells = _layout_cells((0.0, 0.0), 3.0, 0.0)
        cells = children + crossing_cells

        self.assertTrue(_cells_cover_country([cells[0]], Polygon(cells[0])))
        self.assertFalse(
            _cells_cover_country(cells, Polygon([(20, 20), (21, 20), (21, 21)]))
        )

    def test_coverage_score_counts_cells_below_ten_percent(self) -> None:
        cell = [(0, 0), (2, 0), (2, 2), (0, 2)]
        scored = _score_cells(
            [cell],
            [],
            Polygon([(0, 0), (0.4, 0), (0.4, 1), (0, 1)]),
        )

        self.assertEqual(len(scored), 1)
        self.assertAlmostEqual(scored[0][1], 0.1)
        self.assertEqual(_quality(scored), (0, -0.1, -0.1, 1))

    def test_coverage_quality_prioritizes_utilization_before_cell_count(self) -> None:
        lower_use_25 = [( [], 0.10, False)] + [([], 0.5, False)] * 24
        higher_use_24 = [([], 0.15, False)] + [([], 0.5, False)] * 23

        self.assertLess(_quality(higher_use_24), _quality(lower_use_25))

    def test_translation_ranges_include_both_axis_extremes(self) -> None:
        east_west = _linspace(-4.0, 6.0, 5)
        north_south = _linspace(-4.0, 6.0, 5)

        self.assertEqual((east_west[0], east_west[-1]), (-4.0, 6.0))
        self.assertEqual((north_south[0], north_south[-1]), (-4.0, 6.0))
        self.assertIn((1.0, 1.0), list(zip(east_west, north_south)))

    def test_feasible_translation_bounds_allow_west_and_south_offsets(self) -> None:
        grid = Polygon([(-2, -1), (2, -1), (2, 1), (-2, 1)])
        country = Polygon([(-1, -0.5), (1, -0.5), (1, 0.5), (-1, 0.5)])

        bounds = _translation_bounds(grid, country, 1.0, 0.0)

        self.assertIsNotNone(bounds)
        assert bounds is not None
        x_low, x_high, y_low, y_high = bounds
        self.assertLess(x_low, 0)
        self.assertGreater(x_high, 0)
        self.assertLess(y_low, 0)
        self.assertGreater(y_high, 0)

    def test_rotation_and_translation_apply_to_prebuilt_cells(self) -> None:
        original = _layout_cells((0.0, 0.0), 1.0, 0.0)[2]

        transformed = _transform_hexagons(
            original,
            (12.0, -7.0),
            2.0,
            radians(90),
        )

        self.assertEqual(len(transformed), len(original))
        self.assertAlmostEqual(transformed[0][0][0], 12.0, places=7)
        self.assertAlmostEqual(transformed[0][0][1], -7.0 + 2 / 9, places=7)

    def test_third_level_svg_distinguishes_merged_junction_cells(self) -> None:
        parent, second_level, third_level, crossing_cells = _layout_cells(
            (14.0, 49.5), 3.0, 0.0
        )
        fit = GridFit(
            parent=parent,
            second_level=second_level,
            third_level=third_level,
            crossing_cells=crossing_cells,
            scale=1.0,
            angle_degrees=0.0,
            occupied_count=2,
            low_coverage_count=1,
            offset_east_km=0.0,
            offset_north_km=0.0,
            cell_edge_km=10.0,
            cell_area_km2=sqrt(3) / 2 * 100,
            display_cells=[
                (third_level[0], 0.35),
                (crossing_cells[0], 0.04),
            ],
        )
        svg = render_third_level_svg(BOUNDARY_RINGS, fit=fit)

        self.assertIn("Only cells intersecting", svg)
        self.assertIn("1 cells have less than 10 percent", svg)
        self.assertEqual(svg.count('stroke-width="2"'), 2)
        self.assertIn('stroke="#e65100"', svg)
        self.assertNotIn("dominant-baseline=\"central\"", svg)


if __name__ == "__main__":
    unittest.main()
