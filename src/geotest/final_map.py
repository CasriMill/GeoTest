from dataclasses import asdict, dataclass
import json
from math import isfinite
from pathlib import Path
from collections.abc import Sequence

from shapely.geometry import Point

from geotest.boundary import (
    fetch_boundary_data,
    parse_boundary_rings,
    render_boundary_svg,
)
from geotest.hexgrid import Ring
from geotest.tiling import (
    GridAnalysis,
    analyze_hex_tiling,
    project_boundary_to_km,
    project_wgs84_point,
    unproject_km_point,
)


DEFAULT_SETTINGS_PATH = Path("output/czechia_hex_grid_config.json")
DEFAULT_FINAL_MAP_PATH = Path("output/czechia_hex_grid_final.svg")
SETTINGS_VERSION = 1


@dataclass(frozen=True)
class HexGridSettings:
    edge_length_km: float = 41.5
    offset_east_km: float = -29.0
    offset_north_km: float = -10.0
    rotation_degrees: float = 46.5

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(not isfinite(value) for value in values.values()):
            raise ValueError("Grid settings must be finite numbers")
        if self.edge_length_km <= 0:
            raise ValueError("Hexagon edge length must be greater than zero")


def save_settings(settings: HexGridSettings, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": SETTINGS_VERSION, **asdict(settings)}
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_settings(path: Path) -> HexGridSettings:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Grid settings file must contain a JSON object")
    if document.get("version") != SETTINGS_VERSION:
        raise ValueError(
            f"Unsupported grid settings version: {document.get('version')!r}"
        )

    names = (
        "edge_length_km",
        "offset_east_km",
        "offset_north_km",
        "rotation_degrees",
    )
    values = {}
    for name in names:
        value = document.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Grid setting {name!r} must be a number")
        values[name] = float(value)
    return HexGridSettings(**values)


def alphabetic_label(index: int) -> str:
    if index < 0:
        raise ValueError("Label index must not be negative")
    label = ""
    while True:
        index, remainder = divmod(index, 26)
        label = chr(ord("A") + remainder) + label
        if index == 0:
            return label
        index -= 1


def ordered_hex_cells(analysis: GridAnalysis):
    return sorted(
        analysis.cells,
        key=lambda cell: (-cell.polygon.centroid.y, cell.polygon.centroid.x),
    )


def find_cell_label(
    analysis: GridAnalysis,
    wgs84_point: tuple[float, float],
    rings: Sequence[Ring],
) -> str:
    point = Point(project_wgs84_point(rings, wgs84_point))
    matching_indices = [
        index
        for index, cell in enumerate(ordered_hex_cells(analysis))
        if cell.polygon.covers(point)
    ]
    if not matching_indices:
        raise ValueError(
            f"Point {wgs84_point!r} is not covered by an occupied grid cell"
        )
    return alphabetic_label(min(matching_indices))


def render_final_map_svg(
    rings: Sequence[Ring],
    settings: HexGridSettings,
) -> tuple[str, GridAnalysis]:
    country = project_boundary_to_km(rings)
    analysis = analyze_hex_tiling(
        country,
        edge_length_km=settings.edge_length_km,
        offset_east_km=settings.offset_east_km,
        offset_north_km=settings.offset_north_km,
        rotation_degrees=settings.rotation_degrees,
    )
    if not analysis.fully_covered:
        raise ValueError(
            f"Grid leaves {analysis.uncovered_area_km2:.9f} km² of Czechia uncovered"
        )

    ordered_cells = ordered_hex_cells(analysis)
    overlays = [
        (
            [
                unproject_km_point(rings, point)
                for point in cell.polygon.exterior.coords
            ],
            "#555555",
            None,
        )
        for cell in ordered_cells
    ]
    labels = [
        (
            unproject_km_point(
                rings,
                (cell.polygon.centroid.x, cell.polygon.centroid.y),
            ),
            alphabetic_label(index),
        )
        for index, cell in enumerate(ordered_cells)
    ]
    ratios = [cell.coverage_ratio for cell in ordered_cells]
    description = (
        f"Regular hexagonal grid: edge {settings.edge_length_km:.1f} km, "
        f"rotation {settings.rotation_degrees:.1f} degrees, "
        f"east offset {settings.offset_east_km:.1f} km, "
        f"north offset {settings.offset_north_km:.1f} km. "
        f"{len(ordered_cells)} occupied cells; minimum cell coverage "
        f"{min(ratios, default=0):.1%}; full Czechia coverage verified."
    )
    svg = render_boundary_svg(
        rings,
        overlays=overlays,
        labels=labels,
        title="Czech Republic — final labeled hex grid",
        description=description,
    )
    return svg, analysis


def create_final_map(
    output_path: Path = DEFAULT_FINAL_MAP_PATH,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> tuple[Path, GridAnalysis]:
    rings = parse_boundary_rings(fetch_boundary_data())
    settings = load_settings(settings_path)
    svg, analysis = render_final_map_svg(rings, settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return output_path, analysis
