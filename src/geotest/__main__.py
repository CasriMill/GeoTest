import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from geotest.boundary import create_boundary_map
from geotest.final_map import (
    DEFAULT_FINAL_MAP_PATH,
    DEFAULT_SETTINGS_PATH,
    create_final_map,
)
from geotest.hexgrid import create_hex_grid_map, create_third_level_map
from geotest.grid_gui import launch_grid_gui
from geotest.locations import DEFAULT_LOCATIONS_PATH, create_location_json


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="geotest")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("boundary", "grid", "grid3", "gui", "final", "locations"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output SVG path",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="JSON grid settings file used by the final command",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="CSO population reference year (default: latest available year)",
    )
    args = parser.parse_args(argv or [])

    if args.command == "boundary":
        output_path = create_boundary_map(
            args.output or Path("output/czechia_boundary.svg")
        )
        print(f"Boundary map written to {output_path}")
        return

    if args.command == "grid":
        output_path = create_hex_grid_map(
            args.output or Path("output/czechia_hex_grid.svg")
        )
        print(f"Hex grid map written to {output_path}")
        return

    if args.command == "grid3":
        output_path, fit = create_third_level_map(
            args.output or Path("output/czechia_hex_grid_level3.svg")
        )
        print(
            f"Third-level map written to {output_path}: "
            f"scale {fit.scale:.2f}x, rotation {fit.angle_degrees:.2f}°, "
            f"offset {fit.offset_east_km:.1f} km east / "
            f"{fit.offset_north_km:.1f} km north, "
            f"cell edge {fit.cell_edge_km:.1f} km, "
            f"area {fit.cell_area_km2:.1f} km^2, "
            f"{fit.occupied_count} occupied cells "
            f"({fit.low_coverage_count} below 10%)"
        )
        return

    if args.command == "gui":
        launch_grid_gui()
        return

    if args.command == "final":
        output_path, analysis = create_final_map(
            args.output or DEFAULT_FINAL_MAP_PATH,
            args.settings,
        )
        ratios = [cell.coverage_ratio for cell in analysis.cells]
        print(
            f"Final labeled map written to {output_path}: "
            f"{len(analysis.cells)} cells, "
            f"minimum coverage {min(ratios, default=0):.1%}, "
            f"{sum(round(ratio * 100, 1) == 100.0 for ratio in ratios)} "
            "shown as 100.0% inside Czechia"
        )
        return

    if args.command == "locations":
        output_path, document = create_location_json(
            args.output or DEFAULT_LOCATIONS_PATH,
            year=args.year,
        )
        counts = document["counts"]
        print(
            f"Location JSON written to {output_path}: "
            f"{counts['municipalities']} municipalities, "
            f"{counts['aip_aerodromes_and_heliports']} AIP aerodromes/heliports "
            f"({document['population_year']} population data)"
        )
        return

    print("GeoTest project is ready.")


if __name__ == "__main__":
    main(sys.argv[1:])
