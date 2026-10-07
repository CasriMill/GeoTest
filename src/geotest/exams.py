from collections.abc import Sequence
import html
import json
import math
from pathlib import Path
import random

from geotest.boundary import fetch_boundary_data, parse_boundary_rings, render_boundary_svg
from geotest.final_map import (
    DEFAULT_SETTINGS_PATH,
    DEFAULT_FINAL_MAP_PATH,
    alphabetic_label,
    load_settings,
    ordered_hex_cells,
)
from geotest.tiling import (
    analyze_hex_tiling,
    project_boundary_to_km,
    project_wgs84_point,
    unproject_km_point,
)


DEFAULT_EXAM_OUTPUT_DIR = Path("output/exams")
DEFAULT_FINAL_MAP_PATH = Path("output/czechia_hex_grid_final.svg")


def _question_label(record: dict[str, object]) -> object:
    if record.get("category") == "airport":
        icao = record.get("icao")
        if isinstance(icao, str) and icao:
            return icao
    return record["name"]


EXAM_COMPOSITIONS = {
    1: {"settlements_100000_plus": 4, "airports_international": 2},
    2: {
        "settlements_100000_plus": 3,
        "settlements_50000_100000": 2,
        "airports_international_or_military": 2,
    },
    3: {
        "settlements_100000_plus": 1,
        "settlements_50000_100000": 2,
        "settlements_10000_50000": 2,
        "airports_international_or_military": 3,
    },
    4: {
        "settlements_50000_100000": 2,
        "settlements_10000_50000": 4,
        "airports_all": 3,
    },
    5: {"settlements_5000_75000": 6, "airports_all": 4},
}

_OVERLAP_COUNTS = {
    1: {"settlements_100000_plus": 2, "airports_international": 1},
    2: {
        "settlements_100000_plus": 1,
        "settlements_50000_100000": 1,
        "airports_international_or_military": 1,
    },
    3: {
        "settlements_100000_plus": 1,
        "settlements_50000_100000": 1,
        "settlements_10000_50000": 1,
        "airports_international_or_military": 1,
    },
    4: {
        "settlements_50000_100000": 1,
        "settlements_10000_50000": 2,
        "airports_all": 1,
    },
    5: {"settlements_5000_75000": 3, "airports_all": 2},
}


def _in_group(record: dict[str, object], group: str) -> bool:
    if group.startswith("settlements_"):
        if record.get("category") != "sidlo":
            return False
        population = record.get("population")
        if not isinstance(population, int):
            return False
        ranges = {
            "settlements_100000_plus": (100_001, None),
            "settlements_50000_100000": (50_000, 100_000),
            "settlements_10000_50000": (10_000, 50_000),
            "settlements_5000_75000": (5_000, 75_000),
        }
        minimum, maximum = ranges[group]
        return population >= minimum and (
            maximum is None or population < maximum
        )

    if record.get("category") != "airport" or record.get("airport_type") != "aerodrome":
        return False
    categories = record.get("airport_categories")
    if not isinstance(categories, dict):
        return False
    if group == "airports_international":
        return categories.get("international") is True
    if group == "airports_international_or_military":
        return (
            categories.get("international") is True
            or categories.get("military") is True
        )
    return group == "airports_all"


def _has_valid_cell_distribution(records: Sequence[dict[str, object]]) -> bool:
    by_cell: dict[object, list[str]] = {}
    for record in records:
        cell = record.get("cell")
        if not isinstance(cell, str) or not cell:
            return False
        by_cell.setdefault(cell, []).append(str(record.get("category")))
    return all(
        len(categories) == 1
        or (len(categories) == 2 and set(categories) == {"sidlo", "airport"})
        for categories in by_cell.values()
    )


def _load_grid_geometry() -> tuple[list[tuple[str, list[tuple[float, float]]]], dict[str, tuple[float, float]], float] | None:
    try:
        settings = load_settings(DEFAULT_SETTINGS_PATH)
        rings = parse_boundary_rings(fetch_boundary_data())
        country = project_boundary_to_km(rings)
        analysis = analyze_hex_tiling(
            country,
            edge_length_km=settings.edge_length_km,
            offset_east_km=settings.offset_east_km,
            offset_north_km=settings.offset_north_km,
            rotation_degrees=settings.rotation_degrees,
        )
        centers = {
            alphabetic_label(index): cell.polygon.centroid.coords[0]
            for index, cell in enumerate(ordered_hex_cells(analysis))
        }
        return rings, centers, settings.edge_length_km
    except Exception:
        return None


def _record_difficulty_percent(
    item: dict[str, object],
    geometry: tuple[list[tuple[str, list[tuple[float, float]]]], dict[str, tuple[float, float]], float] | None,
) -> str:
    if geometry is None:
        return "—"
    rings, centers, edge_length_km = geometry
    cell = item.get("cell")
    gps = item.get("gps")
    if not isinstance(cell, str) or not cell:
        return "—"
    point = centers.get(cell)
    if point is None or not isinstance(gps, dict):
        return "—"
    longitude = gps.get("longitude")
    latitude = gps.get("latitude")
    if not isinstance(longitude, (int, float)) or not isinstance(latitude, (int, float)):
        return "—"
    projected_point = project_wgs84_point(rings, (float(longitude), float(latitude)))
    distance_km = math.hypot(
        projected_point[0] - point[0],
        projected_point[1] - point[1],
    )
    percent = max(0.0, min(100.0, (distance_km / edge_length_km) * 100.0))
    return f"{percent:.1f}%"


def _summary_label_for_versions(difficulty: int, versions: set[int]) -> str:
    labels = "/".join(
        str(version) if version in versions else "." for version in range(1, 6)
    )
    return f"{difficulty}-{labels}"


def _summary_overview_svg(
    difficulty: int,
    variants: Sequence[tuple[dict[str, object], dict[str, object]]],
) -> str:
    geometry = _load_grid_geometry()
    if geometry is None:
        fallback_map = DEFAULT_FINAL_MAP_PATH.read_text(encoding="utf-8")
        if fallback_map.startswith("<?xml"):
            fallback_map = fallback_map.split("?>", 1)[1].lstrip()
        return fallback_map

    rings, _, _ = geometry
    versioned_locations: dict[str, set[int]] = {}
    coordinates: dict[str, tuple[float, float]] = {}
    for version, (_, answer) in enumerate(variants, start=1):
        for item in answer["answers"]:
            key = str(item.get("location_id"))
            versioned_locations.setdefault(key, set()).add(version)
            gps = item.get("gps")
            if not isinstance(gps, dict):
                continue
            longitude = gps.get("longitude")
            latitude = gps.get("latitude")
            if isinstance(longitude, (int, float)) and isinstance(latitude, (int, float)):
                coordinates[key] = (float(longitude), float(latitude))

    overlays = []
    labels = []
    for location_id, versions in versioned_locations.items():
        gps = coordinates.get(location_id)
        if gps is None:
            continue
        x_km, y_km = project_wgs84_point(rings, gps)
        lon, lat = unproject_km_point(rings, (x_km, y_km))
        radius = 0.006
        hexagon = []
        for index in range(6):
            angle = math.radians(60 * index)
            hexagon.append(
                (
                    lon + radius * math.cos(angle),
                    lat + radius * math.sin(angle),
                )
            )
        overlays.append((hexagon, "#d12d2d", "#fca5a5"))
        labels.append(( (lon, lat), _summary_label_for_versions(difficulty, versions)) )

    if not overlays:
        return "<div class=\"map-placeholder\">Mapa přehledu není dostupná.</div>"

    svg = render_boundary_svg(
        rings,
        overlays=overlays,
        labels=labels,
        title=f"Souhrnná mapa obtížnosti {difficulty}",
        description=(
            f"Přehled všech pozic a variant pro obtížnost {difficulty}. "
            "Dvojtečky označují verze, tečkou absence v dané verzi."
        ),
    )
    return svg.split("?>", 1)[1].lstrip() if svg.startswith("<?xml") else svg


def _build_documents_for_records(
    locations_document: dict[str, object],
    records: Sequence[dict[str, object]],
    *,
    difficulty: int,
    version: int,
    seed: int,
    shared_with_previous_version: int,
) -> tuple[dict[str, object], dict[str, object]]:
    ordered_records = list(records)
    random.Random(seed + difficulty * 100 + version).shuffle(ordered_records)
    questions = [
        {
            "number": number,
            "name": _question_label(record),
            "category": record["category"],
            "location_id": record["id"],
        }
        for number, record in enumerate(ordered_records, start=1)
    ]
    answers = [
        {
            "number": number,
            "location_id": record["id"],
            "name": record["name"],
            "category": record["category"],
            "cell": record["cell"],
            "gps": record.get("gps"),
            "icao": record.get("icao"),
            "population": record.get("population"),
        }
        for number, record in enumerate(ordered_records, start=1)
    ]
    metadata = {
        "schema_version": 1,
        "difficulty": difficulty,
        "version": version,
        "set_id": f"difficulty-{difficulty}-version-{version}",
        "seed": seed,
        "population_year": locations_document.get("population_year"),
        "grid": locations_document.get("grid"),
        "item_count": len(ordered_records),
        "shared_with_previous_version": shared_with_previous_version,
    }
    return {**metadata, "questions": questions}, {**metadata, "answers": answers}


def build_exam_suite(
    locations_document: dict[str, object], *, seed: int = 20261006
) -> dict[int, list[tuple[dict[str, object], dict[str, object]]]]:
    records = locations_document.get("records")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ValueError("Location document must contain a records list")

    candidates = {
        group: [record for record in records if _in_group(record, group)]
        for composition in EXAM_COMPOSITIONS.values()
        for group in composition
    }
    for difficulty, composition in EXAM_COMPOSITIONS.items():
        for group, requested in composition.items():
            if len(candidates[group]) < requested:
                raise ValueError(
                    f"Difficulty {difficulty} needs {requested} records in {group}, "
                    f"but only {len(candidates[group])} are available"
                )

    rng = random.Random(seed)
    suite = {}
    for difficulty, composition in EXAM_COMPOSITIONS.items():
        previous_groups: dict[str, list[dict[str, object]]] = {}
        variants = []
        for version in range(1, 6):
            overlap = _OVERLAP_COUNTS[difficulty] if version > 1 else {}
            selected_groups = None
            for _ in range(10_000):
                attempt_groups = {}
                for group, requested in composition.items():
                    shared_count = overlap.get(group, 0)
                    previous = previous_groups.get(group, [])
                    shared = rng.sample(previous, shared_count)
                    previous_ids = {record["id"] for record in previous}
                    fresh_pool = [
                        record
                        for record in candidates[group]
                        if record["id"] not in previous_ids
                    ]
                    fresh_count = requested - shared_count
                    if len(fresh_pool) < fresh_count:
                        raise ValueError(
                            f"Not enough unused {group} records for difficulty "
                            f"{difficulty}, version {version}"
                        )
                    attempt_groups[group] = [
                        *shared,
                        *rng.sample(fresh_pool, fresh_count),
                    ]
                attempt_records = [
                    record
                    for group_records in attempt_groups.values()
                    for record in group_records
                ]
                if (
                    len({record.get("id") for record in attempt_records})
                    == len(attempt_records)
                    and _has_valid_cell_distribution(attempt_records)
                ):
                    selected_groups = attempt_groups
                    break
            if selected_groups is None:
                raise ValueError(
                    f"Could not satisfy cell-sharing rules for difficulty "
                    f"{difficulty}, version {version}"
                )

            selected_records = [
                record
                for group_records in selected_groups.values()
                for record in group_records
            ]
            student, answer = _build_documents_for_records(
                locations_document,
                selected_records,
                difficulty=difficulty,
                version=version,
                seed=seed,
                shared_with_previous_version=sum(overlap.values()),
            )
            variants.append((student, answer))
            previous_groups = selected_groups
        suite[difficulty] = variants
    return suite


def _student_html(student: dict[str, object], map_svg: str) -> str:
    set_id = html.escape(str(student["set_id"]))
    map_content = map_svg.strip()
    if map_content.startswith("<?xml"):
        map_content = map_content.split("?>", 1)[1].lstrip()
    question_rows = "\n".join(
        "<tr><td>{number}</td><td>{name}</td><td></td><td></td></tr>".format(
            number=question["number"],
            name=html.escape(str(question["name"])),
        )
        for question in student["questions"]
    )
    return f'''<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<title>{set_id}</title>
<style>
@page {{ size: A4 portrait; margin: 10mm; }}
* {{ box-sizing: border-box; }}
body {{ color: #111; font: 10pt Arial, sans-serif; margin: 0; }}
h1 {{ font-size: 15pt; margin: 0 0 2mm; }}
.set-id {{ font-size: 9pt; margin-bottom: 2mm; }}
.map {{ height: 125mm; width: 100%; }}
.map svg {{ display: block; height: 100%; width: 100%; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #333; padding: 1.4mm 2mm; text-align: left; }}
th {{ font-weight: 700; }}
.questions {{ margin-top: 2mm; }}
.questions td {{ height: 7mm; }}
.prediction {{ margin-top: 4mm; }}
.prediction td {{ height: 9mm; }}
</style>
</head>
<body>
<h1>Geografický test</h1>
<div class="set-id">Sada: {set_id}</div>
<div class="map">{map_content}</div>
<table class="questions">
<thead><tr><th>#</th><th>Hledaný objekt</th><th>Přiřazení studenta</th><th>Hodnocení hodnotitele</th></tr></thead>
<tbody>{question_rows}</tbody>
</table>
<table class="prediction">
<tbody><tr><th>Student</th><th>Predikce správná</th><th>Predikce nejistá</th><th>Predikce tipovaná nebo neurčená</th></tr>
<tr><td></td><td></td><td></td><td></td></tr></tbody>
</table>
</body>
</html>
'''


def _teacher_html(
    difficulty: int,
    variants: Sequence[tuple[dict[str, object], dict[str, object]]],
) -> str:
    geometry = _load_grid_geometry()
    summary_map_svg = _summary_overview_svg(difficulty, variants)
    pages = []
    for _, answer in variants:
        answer_rows = "\n".join(
            "<tr><td>{number}</td><td>{name}</td><td>{cell}</td><td>{difficulty_percent}</td><td>{details}</td></tr>".format(
                number=item["number"],
                name=html.escape(str(item["name"])),
                cell=html.escape(str(item["cell"])),
                difficulty_percent=html.escape(
                    _record_difficulty_percent(item, geometry)
                ),
                details=(
                    f"{item['population']:,} obyvatel"
                    if item.get("population") is not None
                    else html.escape(str(item.get("icao") or "letiště"))
                ),
            )
            for item in answer["answers"]
        )
        pages.append(
            f'''<section class="key-page">
<h1>Hodnotitelský klíč — obtížnost {difficulty}</h1>
<div class="set-id">Sada: {html.escape(str(answer["set_id"]))}</div>
<table><thead><tr><th>#</th><th>Hledaný objekt</th><th>Buňka</th><th>Obtížnost</th><th>Údaj</th></tr></thead>
<tbody>{answer_rows}</tbody></table>
</section>'''
        )
    return f'''<!doctype html>
<html lang="cs"><head><meta charset="utf-8">
<title>Hodnotitelský klíč — obtížnost {difficulty}</title>
<style>
@page {{ size: A4 portrait; margin: 15mm; }}
* {{ box-sizing: border-box; }}
body {{ color: #111; font: 10pt Arial, sans-serif; margin: 0; }}
.key-page {{ break-after: page; }}
.key-page:last-child {{ break-after: auto; }}
h1 {{ font-size: 16pt; margin: 0 0 3mm; }}
.set-id {{ margin-bottom: 7mm; }}
.summary-map {{ margin: 0 0 8mm; }}
.summary-map svg {{ display: block; width: 100%; height: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #333; padding: 2mm; text-align: left; }}
</style></head><body><div class="summary-map">{summary_map_svg}</div>{''.join(pages)}</body></html>
'''


def write_exam_suite(
    suite: dict[int, list[tuple[dict[str, object], dict[str, object]]]],
    *,
    map_path: Path = DEFAULT_FINAL_MAP_PATH,
    output_dir: Path = DEFAULT_EXAM_OUTPUT_DIR,
) -> list[Path]:
    if not map_path.is_file():
        raise FileNotFoundError(f"Final labeled map does not exist: {map_path}")
    map_svg = map_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths = []
    for difficulty, variants in suite.items():
        for student, answer in variants:
            student_json, answer_json = write_exam_documents(
                student, answer, output_dir
            )
            student_html = output_dir / f"{student['set_id']}-student.html"
            student_html.write_text(
                _student_html(student, map_svg), encoding="utf-8"
            )
            written_paths.extend((student_json, answer_json, student_html))
        teacher_path = output_dir / f"difficulty-{difficulty}-teacher-key.html"
        teacher_html = _teacher_html(difficulty, variants)
        teacher_path.write_text(teacher_html, encoding="utf-8")
        written_paths.append(teacher_path)
        overview_path = output_dir / f"difficulty-{difficulty}-overview.svg"
        overview_svg = _summary_overview_svg(difficulty, variants)
        if overview_svg:
            overview_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n' + overview_svg,
                encoding="utf-8",
            )
    return written_paths


def build_exam_documents(
    locations_document: dict[str, object],
    *,
    difficulty: int,
    population_minimum: int,
    supplemental_population_minimum: int | None = None,
    supplemental_settlement_count: int = 0,
    airport_category: str,
    airport_count: int,
    seed: int,
    airport_icao_codes: Sequence[str] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    if difficulty < 1:
        raise ValueError("Difficulty must be a positive integer")
    if population_minimum < 0:
        raise ValueError("Minimum population must not be negative")
    if supplemental_population_minimum is not None and (
        supplemental_population_minimum < 0
        or supplemental_population_minimum >= population_minimum
    ):
        raise ValueError(
            "Supplemental population minimum must be nonnegative and below "
            "the primary minimum"
        )
    if supplemental_settlement_count < 0:
        raise ValueError("Supplemental settlement count must not be negative")
    if airport_count < 0:
        raise ValueError("Airport count must not be negative")

    records = locations_document.get("records")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ValueError("Location document must contain a records list")

    settlements = [
        record
        for record in records
        if record.get("category") == "sidlo"
        and isinstance(record.get("population"), int)
        and record["population"] >= population_minimum
    ]
    supplemental_candidates = [
        record
        for record in records
        if supplemental_population_minimum is not None
        and record.get("category") == "sidlo"
        and isinstance(record.get("population"), int)
        and supplemental_population_minimum
        <= record["population"]
        < population_minimum
    ]
    supplemental_candidates.sort(
        key=lambda record: (-record["population"], str(record["name"]))
    )
    if supplemental_settlement_count > len(supplemental_candidates):
        raise ValueError(
            f"Requested {supplemental_settlement_count} supplemental settlements, "
            f"but only {len(supplemental_candidates)} meet the population range"
        )
    supplemental_settlements = supplemental_candidates[
        :supplemental_settlement_count
    ]
    airports = [
        record
        for record in records
        if record.get("category") == "airport"
        and record.get("airport_type") == "aerodrome"
        and isinstance(record.get("airport_categories"), dict)
        and record["airport_categories"].get(airport_category) is True
    ]
    if not settlements:
        raise ValueError(
            f"No settlements meet the minimum population of {population_minimum}"
        )
    if airport_icao_codes is not None:
        airports_by_icao = {record.get("icao"): record for record in airports}
        missing = sorted(set(airport_icao_codes) - set(airports_by_icao))
        if missing:
            raise ValueError(
                f"Selected ICAO codes are not eligible {airport_category} aerodromes: "
                + ", ".join(missing)
            )
        if len(set(airport_icao_codes)) != len(airport_icao_codes):
            raise ValueError("Selected airport ICAO codes must be unique")
        selected_airports = [
            airports_by_icao[icao] for icao in airport_icao_codes
        ]
    else:
        if len(airports) < airport_count:
            raise ValueError(
                f"Requested {airport_count} airports, but only {len(airports)} "
                f"eligible {airport_category} aerodromes are available"
            )
        selected_airports = random.Random(seed).sample(airports, airport_count)

    selected_records = [
        *settlements,
        *supplemental_settlements,
        *selected_airports,
    ]
    if len({record.get("id") for record in selected_records}) != len(
        selected_records
    ):
        raise ValueError("Selected records contain duplicate IDs")

    random.Random(seed).shuffle(selected_records)
    questions = [
        {
            "number": number,
            "name": _question_label(record),
            "category": record["category"],
            "location_id": record["id"],
        }
        for number, record in enumerate(selected_records, start=1)
    ]
    answers = [
        {
            "number": number,
            "location_id": record["id"],
            "name": record["name"],
            "category": record["category"],
            "cell": record["cell"],
            "gps": record["gps"],
            "icao": record.get("icao"),
            "population": record.get("population"),
        }
        for number, record in enumerate(selected_records, start=1)
    ]
    selection = {
        "population_minimum_inclusive": population_minimum,
        "supplemental_population_minimum_inclusive": (
            supplemental_population_minimum
        ),
        "supplemental_settlement_count": len(supplemental_settlements),
        "airport_category": airport_category,
        "airport_icao_codes": [record.get("icao") for record in selected_airports],
        "seed": seed,
    }
    grid = locations_document.get("grid")
    metadata = {
        "schema_version": 1,
        "difficulty": difficulty,
        "version": 1,
        "seed": seed,
        "population_year": locations_document.get("population_year"),
        "selection": selection,
        "grid": grid,
        "item_count": len(questions),
    }
    student_document = {
        **metadata,
        "questions": questions,
    }
    answer_document = {
        **metadata,
        "answers": answers,
    }
    return student_document, answer_document


def write_exam_documents(
    student_document: dict[str, object],
    answer_document: dict[str, object],
    output_dir: Path = DEFAULT_EXAM_OUTPUT_DIR,
) -> tuple[Path, Path]:
    difficulty = student_document["difficulty"]
    version = student_document["version"]
    output_dir.mkdir(parents=True, exist_ok=True)
    student_path = output_dir / (
        f"difficulty-{difficulty}-version-{version}-student.json"
    )
    answer_path = output_dir / (
        f"difficulty-{difficulty}-version-{version}-teacher-key.json"
    )
    for path, document in (
        (student_path, student_document),
        (answer_path, answer_document),
    ):
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
    return student_path, answer_path
