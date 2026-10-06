from dataclasses import dataclass
from math import ceil, cos, floor, radians, sin, sqrt
from collections.abc import Sequence

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from geotest.hexgrid import Coordinate, Ring


KILOMETERS_PER_DEGREE = 111.32


@dataclass(frozen=True)
class CellIntersection:
    polygon: Polygon
    country_area_km2: float
    coverage_ratio: float


@dataclass(frozen=True)
class GridAnalysis:
    country: BaseGeometry
    cells: list[CellIntersection]
    fully_covered: bool
    uncovered_area_km2: float
    edge_length_km: float
    cell_area_km2: float


def project_boundary_to_km(rings: Sequence[Ring]) -> BaseGeometry:
    center_lon, center_lat, longitude_scale = _projection_parameters(rings)

    outer_polygons = [
        Polygon(
            [
                (lon * longitude_scale, lat * KILOMETERS_PER_DEGREE)
                for lon, lat in ring
            ]
        )
        for role, ring in rings
        if role == "outer"
    ]
    holes = [
        Polygon(
            [
                (lon * longitude_scale, lat * KILOMETERS_PER_DEGREE)
                for lon, lat in ring
            ]
        )
        for role, ring in rings
        if role == "inner"
    ]
    country = unary_union(outer_polygons)
    if holes:
        country = country.difference(unary_union(holes))
    if not country.is_valid:
        country = country.buffer(0)
    return translate(
        country,
        xoff=-center_lon * longitude_scale,
        yoff=-center_lat * KILOMETERS_PER_DEGREE,
    )


def unproject_km_point(
    rings: Sequence[Ring],
    point: tuple[float, float],
) -> tuple[float, float]:
    center_lon, center_lat, longitude_scale = _projection_parameters(rings)
    return (
        point[0] / longitude_scale + center_lon,
        point[1] / KILOMETERS_PER_DEGREE + center_lat,
    )


def project_wgs84_point(
    rings: Sequence[Ring],
    point: tuple[float, float],
) -> tuple[float, float]:
    center_lon, center_lat, longitude_scale = _projection_parameters(rings)
    return (
        (point[0] - center_lon) * longitude_scale,
        (point[1] - center_lat) * KILOMETERS_PER_DEGREE,
    )


def _projection_parameters(
    rings: Sequence[Ring],
) -> tuple[float, float, float]:
    outer_points = [
        point
        for role, ring in rings
        if role == "outer"
        for point in ring
    ]
    if not outer_points:
        raise ValueError("Boundary data has no outer ring")

    center_lon = (
        min(lon for lon, _ in outer_points)
        + max(lon for lon, _ in outer_points)
    ) / 2
    center_lat = (
        min(lat for _, lat in outer_points)
        + max(lat for _, lat in outer_points)
    ) / 2
    longitude_scale = KILOMETERS_PER_DEGREE * cos(radians(center_lat))
    return center_lon, center_lat, longitude_scale


def analyze_hex_tiling(
    country: BaseGeometry,
    edge_length_km: float,
    offset_east_km: float = 0.0,
    offset_north_km: float = 0.0,
    rotation_degrees: float = 0.0,
) -> GridAnalysis:
    if edge_length_km <= 0:
        raise ValueError("Hexagon edge length must be greater than zero")

    side = edge_length_km
    rotation = radians(rotation_degrees)
    cosine = cos(rotation)
    sine = sin(rotation)
    min_x, min_y, max_x, max_y = country.bounds
    anchor = (
        (min_x + max_x) / 2 + offset_east_km,
        (min_y + max_y) / 2 + offset_north_km,
    )
    axial_corners = [
        _to_axial((x - anchor[0], y - anchor[1]), cosine, sine, side)
        for x in (min_x, max_x)
        for y in (min_y, max_y)
    ]
    q_min = floor(min(q for q, _ in axial_corners)) - 2
    q_max = ceil(max(q for q, _ in axial_corners)) + 2
    r_min = floor(min(r for _, r in axial_corners)) - 2
    r_max = ceil(max(r for _, r in axial_corners)) + 2

    cells: list[CellIntersection] = []
    for q in range(q_min, q_max + 1):
        for r in range(r_min, r_max + 1):
            local_x = sqrt(3) * side * (q + r / 2)
            local_y = 1.5 * side * r
            center_x = anchor[0] + cosine * local_x - sine * local_y
            center_y = anchor[1] + sine * local_x + cosine * local_y
            vertices = [
                (
                    center_x + side * cos(rotation + radians(30 + 60 * index)),
                    center_y + side * sin(rotation + radians(30 + 60 * index)),
                )
                for index in range(6)
            ]
            polygon = Polygon(vertices)
            intersection_area = polygon.intersection(country).area
            if intersection_area <= 1e-9:
                continue
            cells.append(
                CellIntersection(
                    polygon=polygon,
                    country_area_km2=intersection_area,
                    coverage_ratio=intersection_area / polygon.area,
                )
            )

    union = unary_union([cell.polygon for cell in cells])
    uncovered_area = country.difference(union).area
    tolerance = max(country.area * 1e-10, 1e-8)
    return GridAnalysis(
        country=country,
        cells=cells,
        fully_covered=uncovered_area <= tolerance,
        uncovered_area_km2=uncovered_area,
        edge_length_km=edge_length_km,
        cell_area_km2=3 * sqrt(3) / 2 * side**2,
    )


def _to_axial(
    point: tuple[float, float],
    cosine: float,
    sine: float,
    side: float,
) -> tuple[float, float]:
    x = cosine * point[0] + sine * point[1]
    y = -sine * point[0] + cosine * point[1]
    r = 2 * y / (3 * side)
    q = x / (sqrt(3) * side) - r / 2
    return q, r
