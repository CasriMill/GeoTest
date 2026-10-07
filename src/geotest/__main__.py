import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from geotest.boundary import create_boundary_map
from geotest.exams import (
    DEFAULT_EXAM_OUTPUT_DIR,
    build_exam_documents,
    build_exam_suite,
    write_exam_documents,
    write_exam_suite,
)
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
        choices=(
            "boundary",
            "grid",
            "grid3",
            "gui",
            "final",
            "locations",
            "exam",
            "exam-suite",
        ),
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
    parser.add_argument(
        "--difficulty",
        type=int,
        default=1,
        help="exam difficulty level",
    )
    parser.add_argument(
        "--population-minimum",
        type=int,
        default=100_000,
        help="inclusive primary municipality population threshold",
    )
    parser.add_argument(
        "--supplemental-population-minimum",
        type=int,
        help="inclusive lower threshold for supplemental settlements",
    )
    parser.add_argument(
        "--supplemental-settlement-count",
        type=int,
        default=0,
        help="number of additional settlements from below the primary threshold",
    )
    parser.add_argument(
        "--airport-category",
        choices=("international", "civil", "sport", "military"),
        default="international",
        help="airport category to select",
    )
    parser.add_argument(
        "--airport-count",
        type=int,
        default=2,
        help="number of airports to sample",
    )
    parser.add_argument(
        "--airport-icao",
        nargs="*",
        help="explicit airport ICAO codes instead of a random sample",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261006,
        help="seed for reproducible airport and question ordering",
    )
    parser.add_argument(
        "--exam-output-dir",
        type=Path,
        default=DEFAULT_EXAM_OUTPUT_DIR,
        help="directory for generated exam files",
    )
    parser.add_argument(
        "--locations-json",
        type=Path,
        default=DEFAULT_LOCATIONS_PATH,
        help="JSON catalogue used to create exam sets",
    )
    parser.add_argument(
        "--exam-map",
        type=Path,
        default=DEFAULT_FINAL_MAP_PATH,
        help="existing labeled SVG map embedded in printable student sheets",
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
            f"{counts['aip_aerodromes']} AIP aerodromes "
            f"({document['population_year']} population data)"
        )
        return

    if args.command == "exam-suite":
        locations_document = json.loads(
            args.locations_json.read_text(encoding="utf-8")
        )
        suite = build_exam_suite(locations_document, seed=args.seed)
        write_exam_suite(
            suite,
            map_path=args.exam_map,
            output_dir=args.exam_output_dir,
        )
        print(
            f"Exam suite written to {args.exam_output_dir}: "
            "5 difficulties, 5 variants each"
        )
        return

    if args.command == "exam":
        locations_document = json.loads(
            args.locations_json.read_text(encoding="utf-8")
        )
        student_document, answer_document = build_exam_documents(
            locations_document,
            difficulty=args.difficulty,
            population_minimum=args.population_minimum,
            supplemental_population_minimum=args.supplemental_population_minimum,
            supplemental_settlement_count=args.supplemental_settlement_count,
            airport_category=args.airport_category,
            airport_count=args.airport_count,
            seed=args.seed,
            airport_icao_codes=args.airport_icao,
        )
        student_path, answer_path = write_exam_documents(
            student_document,
            answer_document,
            args.exam_output_dir,
        )
        print(
            f"Exam set written: {student_path} and {answer_path} "
            f"({student_document['item_count']} items, seed {args.seed})"
        )
        return

    print("GeoTest project is ready.")


if __name__ == "__main__":
    main(sys.argv[1:])
