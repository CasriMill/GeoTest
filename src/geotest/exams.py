from collections.abc import Sequence
import json
from pathlib import Path
import random


DEFAULT_EXAM_OUTPUT_DIR = Path("output/exams")


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
            "name": record["name"],
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
