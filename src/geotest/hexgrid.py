from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from math import atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path
from typing import Callable

from shapely.affinity import affine_transform
from shapely.geometry import Polygon
from shapely.ops import unary_union

from geotest.boundary import fetch_boundary_data, parse_boundary_rings, render_boundary_svg


Coordinate = tuple[float, float]
Ring = tuple[str, Sequence[Coordinate]]
Hexagon = list[Coordinate]

CHILD_STROKES = ("#c62828",) + ("#1565c0",) * 7


@dataclass(frozen=True)
class GridFit:
    parent: Hexagon
    second_level: list[Hexagon]
    third_level: list[Hexagon]
    crossing_cells: list[Hexagon]
    scale: float
    angle_degrees: float
    occupied_count: int
    low_coverage_count: int
    offset_east_km: float
    offset_north_km: float
    cell_edge_km: float
    cell_area_km2: float
    display_cells: list[tuple[Hexagon, float]]


def _projector(rings: Sequence[Ring]):
    outer_points = [
        point
        for role, ring in rings
        if role == "outer"
        for point in ring
    ]
    if not outer_points:
        raise ValueError("Boundary data has no outer ring")
    center_lon = (min(lon for lon, _ in outer_points) + max(lon for lon, _ in outer_points)) / 2
    center_lat = (min(lat for _, lat in outer_points) + max(lat for _, lat in outer_points)) / 2
    x_scale = cos(radians(center_lat))

    def project(point: Coordinate) -> Coordinate:
        return ((point[0] - center_lon) * x_scale, point[1] - center_lat)

    def unproject(point: Coordinate) -> Coordinate:
        return (point[0] / x_scale + center_lon, point[1] + center_lat)

    return [project(point) for point in outer_points], project, unproject


def fit_hexagon_and_seven_children(
    rings: Sequence[Ring],
) -> tuple[Hexagon, list[Hexagon]]:
    """Fit an enclosing regular hexagon and seven touching child hexagons."""
    projected_boundary, _, unproject = _projector(rings)
    best_angle = 0.0
    center = (0.0, 0.0)
    best_apothem = float("inf")
    for step in range(120):
        angle = radians(step * 0.5)
        apothem, candidate_center = _fit_at_angle(projected_boundary, angle)
        if apothem < best_apothem:
            best_apothem = apothem
            best_angle = angle
            center = candidate_center

    coarse_angle = best_angle
    for step in range(-10, 11):
        angle = (coarse_angle + radians(step * 0.05)) % radians(60)
        apothem, candidate_center = _fit_at_angle(projected_boundary, angle)
        if apothem < best_apothem:
            best_apothem = apothem
            best_angle = angle
            center = candidate_center

    side = 2 * best_apothem / sqrt(3)
    parent_projected = _hex_vertices(center, side, best_angle)
    child_side = side / 3
    neighbor_distance = sqrt(3) * child_side
    child_centers = [center] + [
        (
            center[0] + neighbor_distance * cos(best_angle + radians(30 + 60 * index)),
            center[1] + neighbor_distance * sin(best_angle + radians(30 + 60 * index)),
        )
        for index in range(6)
    ]
    children_projected = [
        _hex_vertices(child_center, child_side, best_angle)
        for child_center in child_centers
    ]

    return (
        [unproject(point) for point in parent_projected],
        [
            [unproject(point) for point in child]
            for child in children_projected
        ],
    )


def fit_third_level(
    rings: Sequence[Ring],
) -> tuple[Hexagon, list[Hexagon], list[Hexagon], list[Hexagon]]:
    """Return optimized parent, seven cells, 49 children, and six merged cells."""
    fit = optimize_third_level(rings)
    return fit.parent, fit.second_level, fit.third_level, fit.crossing_cells


def optimize_third_level(rings: Sequence[Ring]) -> GridFit:
    projected_boundary, project, unproject = _projector(rings)
    projected_rings = [
        (role, [project(point) for point in ring])
        for role, ring in rings
    ]
    country = _country_geometry(projected_rings)
    template_cells = _layout_cells((0.0, 0.0), 1.0, 0.0)
    coverage_template = unary_union(
        [
            Polygon(cell)
            for cell in template_cells[2] + template_cells[3]
        ]
    )
    best: tuple[
        tuple[int, float, float, int],
        float,
        float,
        Coordinate,
        tuple[list[Hexagon], ...],
        list[tuple[Hexagon, float, bool]],
    ] | None = None

    def evaluate(
        angle: float,
        scale: float,
        parent_side: float,
        center: Coordinate,
    ) -> None:
        nonlocal best
        transformed_coverage = _transform_geometry(
            coverage_template,
            center,
            parent_side,
            angle,
        )
        if not transformed_coverage.covers(country):
            return

        cells = (
            _transform_hexagon(
                template_cells[0],
                center,
                parent_side,
                angle,
            ),
            *(
                _transform_hexagons(hexagons, center, parent_side, angle)
                for hexagons in template_cells[1:]
            ),
        )
        scored_cells = _score_cells(cells[2], cells[3], country)
        quality = _quality(scored_cells)
        candidate = (quality, scale, angle, center, cells, scored_cells)
        if best is None or candidate[0:2] < best[0:2]:
            best = candidate

    def search_translations(
        angle: float,
        scale: float,
        steps: int,
        fraction_center: Coordinate | None = None,
        window_fraction: float = 1.0,
    ) -> None:
        min_apothem, _ = _fit_at_angle(projected_boundary, angle)
        parent_side = 2 * min_apothem / sqrt(3) * scale
        bounds = _translation_bounds(
            coverage_template,
            country,
            parent_side,
            angle,
        )
        if bounds is None:
            return
        x_low, x_high, y_low, y_high = bounds
        if fraction_center is None:
            x_start, x_end = x_low, x_high
            y_start, y_end = y_low, y_high
        else:
            x_span, y_span = x_high - x_low, y_high - y_low
            x_middle = x_low + fraction_center[0] * x_span
            y_middle = y_low + fraction_center[1] * y_span
            x_radius = x_span * window_fraction
            y_radius = y_span * window_fraction
            x_start = max(x_low, x_middle - x_radius)
            x_end = min(x_high, x_middle + x_radius)
            y_start = max(y_low, y_middle - y_radius)
            y_end = min(y_high, y_middle + y_radius)
        x_offsets = _linspace(x_start, x_end, steps)
        y_offsets = _linspace(y_start, y_end, steps)
        for x_offset in x_offsets:
            for y_offset in y_offsets:
                evaluate(
                    angle,
                    scale,
                    parent_side,
                    (x_offset, y_offset),
                )

    coarse_scales = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5)
    for angle_step in range(12):
        angle = radians(angle_step * 5)
        for scale in coarse_scales:
            search_translations(angle, scale, 7)

    if best is None:
        raise ValueError(
            "No translated and rotated grid in the 1.0x–1.5x range fully "
            "covers the country; increase the scale range or change the grid topology"
        )

    _, coarse_scale, coarse_angle, coarse_center, _, _ = best
    coarse_side = (
        2
        * _fit_at_angle(projected_boundary, coarse_angle)[0]
        / sqrt(3)
        * coarse_scale
    )
    coarse_bounds = _translation_bounds(
        coverage_template,
        country,
        coarse_side,
        coarse_angle,
    )
    if coarse_bounds is None:
        raise ValueError("Best coarse grid has no feasible translation bounds")
    x_low, x_high, y_low, y_high = coarse_bounds
    coarse_fraction = (
        0.5 if x_high == x_low else (coarse_center[0] - x_low) / (x_high - x_low),
        0.5 if y_high == y_low else (coarse_center[1] - y_low) / (y_high - y_low),
    )
    for angle_step in range(-10, 11):
        angle = (coarse_angle + radians(angle_step * 0.5)) % radians(60)
        for scale_step in range(-5, 6):
            scale = round(coarse_scale + scale_step / 100, 2)
            if not 1.0 <= scale <= 1.5:
                continue
            search_translations(
                angle,
                scale,
                7,
                fraction_center=coarse_fraction,
                window_fraction=1 / 6,
            )

    if best is None:
        raise ValueError("Grid fitting unexpectedly lost its best candidate")

    quality, scale, angle, center, cells, scored_cells = best
    parent, second_level, third_level, crossing_cells = cells
    edge_start, edge_end = third_level[0][:2]
    cell_edge_km = sqrt(
        (edge_end[0] - edge_start[0]) ** 2
        + (edge_end[1] - edge_start[1]) ** 2
    ) * 111.32
    return GridFit(
        parent=[unproject(point) for point in parent],
        second_level=[
            [unproject(point) for point in hexagon]
            for hexagon in second_level
        ],
        third_level=[
            [unproject(point) for point in hexagon]
            for hexagon in third_level
        ],
        crossing_cells=[
            [unproject(point) for point in hexagon]
            for hexagon in crossing_cells
        ],
        scale=scale,
        angle_degrees=degrees(angle) % 60,
        occupied_count=len(scored_cells),
        low_coverage_count=quality[0],
        offset_east_km=center[0] * 111.32,
        offset_north_km=center[1] * 111.32,
        cell_edge_km=cell_edge_km,
        cell_area_km2=sqrt(3) / 2 * cell_edge_km**2,
        display_cells=[
            ([unproject(point) for point in hexagon], coverage)
            for hexagon, coverage, _ in scored_cells
        ],
    )


def _linspace(start: float, end: float, count: int) -> list[float]:
    if count <= 1 or abs(end - start) < 1e-12:
        return [(start + end) / 2]
    return [
        start + (end - start) * index / (count - 1)
        for index in range(count)
    ]


def _transform_hexagons(
    hexagons: Sequence[Hexagon],
    center: Coordinate,
    scale: float,
    angle: float,
) -> list[Hexagon]:
    return [
        _transform_hexagon(hexagon, center, scale, angle)
        for hexagon in hexagons
    ]


def _transform_hexagon(
    hexagon: Hexagon,
    center: Coordinate,
    scale: float,
    angle: float,
) -> Hexagon:
    cosine = cos(angle) * scale
    sine = sin(angle) * scale
    return [
        (
            center[0] + cosine * x - sine * y,
            center[1] + sine * x + cosine * y,
        )
        for x, y in hexagon
    ]


def _transform_geometry(
    geometry,
    center: Coordinate,
    scale: float,
    angle: float,
):
    cosine = cos(angle) * scale
    sine = sin(angle) * scale
    return affine_transform(
        geometry,
        [cosine, -sine, sine, cosine, center[0], center[1]],
    )


def _translation_bounds(
    geometry,
    country,
    scale: float,
    angle: float,
) -> tuple[float, float, float, float] | None:
    rotated = _transform_geometry(geometry, (0.0, 0.0), scale, angle)
    min_x, min_y, max_x, max_y = rotated.bounds
    country_min_x, country_min_y, country_max_x, country_max_y = country.bounds
    x_low, x_high = country_max_x - max_x, country_min_x - min_x
    y_low, y_high = country_max_y - max_y, country_min_y - min_y
    if x_low > x_high or y_low > y_high:
        return None
    return x_low, x_high, y_low, y_high


def _layout_cells(
    center: Coordinate,
    parent_side: float,
    angle: float,
) -> tuple[list[Hexagon], list[Hexagon], list[Hexagon], list[Hexagon]]:
    parent = _hex_vertices(center, parent_side, angle)
    second_side = parent_side / 3
    neighbor_distance = sqrt(3) * second_side
    second_centers = [center] + [
        (
            center[0] + neighbor_distance * cos(angle + radians(30 + 60 * index)),
            center[1] + neighbor_distance * sin(angle + radians(30 + 60 * index)),
        )
        for index in range(6)
    ]
    second_level = [
        _hex_vertices(cell_center, second_side, angle)
        for cell_center in second_centers
    ]

    third_level: list[Hexagon] = []
    vertex_owners: dict[tuple[float, float], list[Coordinate]] = {}
    for hexagon in second_level:
        child_side = second_side / 3
        child_distance = sqrt(3) * child_side
        child_centers = [_polygon_center(hexagon)] + [
            (
                _polygon_center(hexagon)[0]
                + child_distance * cos(angle + radians(30 + 60 * index)),
                _polygon_center(hexagon)[1]
                + child_distance * sin(angle + radians(30 + 60 * index)),
            )
            for index in range(6)
        ]
        third_level.extend(
            _hex_vertices(child_center, child_side, angle)
            for child_center in child_centers
        )
        for vertex in hexagon:
            key = (round(vertex[0], 9), round(vertex[1], 9))
            vertex_owners.setdefault(key, []).append(vertex)

    junctions = [
        _polygon_center(vertices)
        for vertices in vertex_owners.values()
        if len(vertices) == 3
    ]
    merged_side = parent_side / 9
    crossing_cells = [
        _hex_vertices(junction, merged_side, angle)
        for junction in junctions
    ]
    return parent, second_level, third_level, crossing_cells


def _country_geometry(rings: Sequence[Ring]):
   outers = [
       Polygon(ring)
       for role, ring in rings
       if role == "outer"
   ]
   if not outers:
       raise ValueError("Boundary data has no outer ring")
   country = unary_union(outers)
   holes = [
       Polygon(ring)
       for role, ring in rings
       if role == "inner"
   ]
   if holes:
       country = country.difference(unary_union(holes))
   if not country.is_valid:
       country = country.buffer(0)
   return country


def _cells_cover_country(
   cells: Sequence[Hexagon],
   country,
) -> bool:
   cell_polygons = [Polygon(cell) for cell in cells]
   return unary_union(cell_polygons).covers(country)


def _transformed_grid_covers_country(
   coverage_template,
   country,
   center: Coordinate,
   parent_side: float,
   angle: float,
) -> bool:
   cosine = cos(angle) * parent_side
   sine = sin(angle) * parent_side
   transformed = affine_transform(
       coverage_template,
       [
           cosine,
           -sine,
           sine,
           cosine,
           center[0],
           center[1],
       ],
   )
   return transformed.covers(country)


def _score_cells(
   third_level: Sequence[Hexagon],
   crossing_cells: Sequence[Hexagon],
   country,
) -> list[tuple[Hexagon, float, bool]]:
   scored: list[tuple[Hexagon, float, bool]] = []
   for is_merged, cells in ((False, third_level), (True, crossing_cells)):
       for cell in cells:
           cell_polygon = Polygon(cell)
           intersection_area = cell_polygon.intersection(country).area
           if intersection_area <= max(country.area * 1e-12, 1e-14):
               continue
           scored.append(
               (cell, intersection_area / cell_polygon.area, is_merged)
           )
   return scored


def _quality(
   scored_cells: Sequence[tuple[Hexagon, float, bool]],
) -> tuple[int, float, float, int]:
   coverage_ratios = [coverage for _, coverage, _ in scored_cells]
   low_coverage_count = sum(ratio < 0.10 for ratio in coverage_ratios)
   if not coverage_ratios:
       return (0, 0.0, 0.0, 0)
   return (
       low_coverage_count,
       -min(coverage_ratios),
       -sum(coverage_ratios) / len(coverage_ratios),
       len(coverage_ratios),
   )


def _encloses_points(
    points: Sequence[Coordinate],
    center: Coordinate,
    apothem: float,
    angle: float,
) -> bool:
    for index in range(3):
        nx = cos(angle + radians(30 + 60 * index))
        ny = sin(angle + radians(30 + 60 * index))
        projections = [(x - center[0]) * nx + (y - center[1]) * ny for x, y in points]
        if max(projections) > apothem + 1e-8 or min(projections) < -apothem - 1e-8:
            return False
    return True


def _polygon_center(points: Sequence[Coordinate]) -> Coordinate:
    return (
        sum(x for x, _ in points) / len(points),
        sum(y for _, y in points) / len(points),
    )


def _hex_angle(
    parent: Hexagon,
    project: Callable[[Coordinate], Coordinate],
) -> float:
    vertices = [project(vertex) for vertex in parent]
    center = _polygon_center(vertices)
    return atan2(
        vertices[0][1] - center[1],
        vertices[0][0] - center[0],
    )


def _fit_at_angle(
    points: Sequence[Coordinate],
    angle: float,
) -> tuple[float, Coordinate]:
    normals = [
        (cos(angle + radians(30 + 60 * index)), sin(angle + radians(30 + 60 * index)))
        for index in range(3)
    ]
    constraints: list[tuple[float, float, float, float]] = []
    for nx, ny in normals:
        projections = [x * nx + y * ny for x, y in points]
        constraints.extend(
            [
                (-nx, -ny, -1.0, -max(projections)),
                (nx, ny, -1.0, min(projections)),
            ]
        )

    best_apothem = float("inf")
    best_center = (0.0, 0.0)
    for active_constraints in combinations(constraints, 3):
        solution = _solve_three(active_constraints)
        if solution is None:
            continue
        center_x, center_y, apothem = solution
        if apothem < -1e-9:
            continue
        if all(
            a * center_x + b * center_y + c * apothem <= d + 1e-9
            for a, b, c, d in constraints
        ) and apothem < best_apothem:
            best_apothem = max(0.0, apothem)
            best_center = (center_x, center_y)

    if best_apothem == float("inf"):
        raise ValueError("Could not fit a hexagon around the boundary")
    return best_apothem, best_center


def _solve_three(
    constraints: Sequence[tuple[float, float, float, float]],
) -> tuple[float, float, float] | None:
    matrix = [list(constraint) for constraint in constraints]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-12:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(3):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(matrix[row], matrix[column])
            ]
    return matrix[0][3], matrix[1][3], matrix[2][3]


def _hex_vertices(center: Coordinate, side: float, angle: float) -> Hexagon:
    return [
        (
            center[0] + side * cos(angle + radians(60 * index)),
            center[1] + side * sin(angle + radians(60 * index)),
        )
        for index in range(6)
    ]


def render_hex_grid_svg(rings: Sequence[Ring]) -> str:
    parent, children = fit_hexagon_and_seven_children(rings)
    overlays = [(parent, CHILD_STROKES[0], None)] + [
        (child, CHILD_STROKES[index + 1], None)
        for index, child in enumerate(children)
    ]
    return render_boundary_svg(
        rings,
        overlays=overlays,
        title="Czech Republic — first hex grid level",
        description=(
            "Red outline: parent hexagon enclosing Czechia. Blue outlines: "
            "seven equal touching child hexagons. Boundary from OpenStreetMap."
        ),
    )


def render_third_level_svg(
    rings: Sequence[Ring],
    fit: GridFit | None = None,
) -> str:
    fit = fit or optimize_third_level(rings)
    overlays = [
        (hexagon, "#e65100" if coverage < 0.10 else "#555555", None)
        for hexagon, coverage in fit.display_cells
    ]
    minimum_coverage = min(
        (coverage for _, coverage in fit.display_cells),
        default=0.0,
    )
    return render_boundary_svg(
        rings,
        overlays=overlays,
        title=(
            "Czech Republic — occupied hex cells "
            f"({fit.occupied_count} cells)"
        ),
        description=(
            f"Grid scale {fit.scale:.2f} of the minimum enclosing parent, "
            f"rotated {fit.angle_degrees:.2f} degrees and offset "
            f"{fit.offset_east_km:.1f} km east, {fit.offset_north_km:.1f} km "
            "north from the projected boundary origin. Only cells intersecting "
            f"Cell edge is approximately {fit.cell_edge_km:.1f} km and area "
            f"{fit.cell_area_km2:.1f} km². "
            f"Czechia are shown. {fit.low_coverage_count} "
            "cells have less than 10 percent of their area inside Czechia; "
            f"minimum cell coverage is {minimum_coverage:.1%}. The cells fully "
            "cover the country. Boundary from OpenStreetMap."
        ),
    )


def create_hex_grid_map(output_path: Path) -> Path:
    rings = parse_boundary_rings(fetch_boundary_data())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_hex_grid_svg(rings), encoding="utf-8")
    return output_path


def create_third_level_map(output_path: Path) -> tuple[Path, GridFit]:
    rings = parse_boundary_rings(fetch_boundary_data())
    fit = optimize_third_level(rings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_third_level_svg(rings, fit), encoding="utf-8")
    return output_path, fit
