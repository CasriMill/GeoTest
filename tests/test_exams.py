import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from geotest.exams import (
    EXAM_COMPOSITIONS,
    build_exam_documents,
    build_exam_suite,
    write_exam_suite,
)


def _matches_group(record: dict[str, object], group: str) -> bool:
    if group.startswith("settlements_"):
        if record.get("category") != "sidlo":
            return False
        population = record.get("population")
        if not isinstance(population, int):
            return False
        ranges = {
            "settlements_100000_plus": (100_000, None, False),
            "settlements_50000_100000": (50_000, 100_000, True),
            "settlements_10000_50000": (10_000, 50_000, True),
            "settlements_5000_75000": (5_000, 75_000, True),
        }
        minimum, maximum, inclusive = ranges[group]
        return (population >= minimum if inclusive else population > minimum) and (
            maximum is None or population < maximum
        )
    if record.get("category") != "airport" or record.get("airport_type") != "aerodrome":
        return False
    categories = record.get("airport_categories", {})
    if group == "airports_international":
        return categories.get("international") is True
    if group == "airports_international_or_military":
        return (
            categories.get("international") is True
            or categories.get("military") is True
        )
    return group == "airports_all"


class ExamSetTests(unittest.TestCase):
    def test_builds_complete_printable_suite_from_project_catalogue(self) -> None:
        root = Path(__file__).resolve().parents[1]
        locations = json.loads(
            (root / "data" / "locations.json").read_text(encoding="utf-8")
        )
        records_by_id = {record["id"]: record for record in locations["records"]}
        suite = build_exam_suite(locations, seed=17)

        self.assertEqual(set(suite), set(range(1, 6)))
        for difficulty, variants in suite.items():
            self.assertEqual(len(variants), 5)
            expected_count = sum(EXAM_COMPOSITIONS[difficulty].values())
            for version, (student, answer) in enumerate(variants, start=1):
                self.assertEqual(student["item_count"], expected_count)
                self.assertEqual(student["version"], version)
                selected = [
                    records_by_id[question["location_id"]]
                    for question in student["questions"]
                ]
                questions_by_id = {
                    question["location_id"]: question
                    for question in student["questions"]
                }
                for record in selected:
                    expected_label = (
                        record["icao"]
                        if record["category"] == "airport"
                        else record["name"]
                    )
                    self.assertEqual(
                        questions_by_id[record["id"]]["name"], expected_label
                    )
                for group, expected_group_count in EXAM_COMPOSITIONS[
                    difficulty
                ].items():
                    self.assertEqual(
                        sum(_matches_group(record, group) for record in selected),
                        expected_group_count,
                        f"difficulty {difficulty}: {group}",
                    )
                by_cell = {}
                for record in selected:
                    by_cell.setdefault(record["cell"], []).append(record)
                self.assertTrue(
                    all(
                        len(cell_records) == 1
                        or (
                            len(cell_records) == 2
                            and {record["category"] for record in cell_records}
                            == {"sidlo", "airport"}
                        )
                        for cell_records in by_cell.values()
                    )
                )
                if version > 1:
                    previous_ids = {
                        question["location_id"]
                        for question in variants[version - 2][0]["questions"]
                    }
                    current_ids = {
                        question["location_id"]
                        for question in student["questions"]
                    }
                    self.assertEqual(
                        len(previous_ids & current_ids), expected_count // 2
                    )
                self.assertEqual(len(answer["answers"]), expected_count)
            self.assertEqual(build_exam_suite(locations, seed=17), suite)

        with TemporaryDirectory() as temporary_dir:
            output_dir = Path(temporary_dir)
            paths = write_exam_suite(
                suite,
                map_path=root / "output" / "czechia_hex_grid_final.svg",
                output_dir=output_dir,
            )
            student_page = (
                output_dir / "difficulty-1-version-1-student.html"
            ).read_text(encoding="utf-8")
            teacher_page = (
                output_dir / "difficulty-1-teacher-key.html"
            ).read_text(encoding="utf-8")
            self.assertEqual(len(paths), 80)
            self.assertIn("@page { size: A4 portrait", student_page)
            self.assertIn("Predikce tipovaná nebo neurčená", student_page)
            self.assertIn("<svg xmlns=", student_page)
            self.assertIn("Obtížnost", teacher_page)
            self.assertTrue((output_dir / "difficulty-1-overview.svg").is_file())
            for version in range(1, 6):
                self.assertIn(
                    f"difficulty-1-version-{version}", teacher_page
                )

    def test_builds_reproducible_filtered_student_and_answer_documents(self) -> None:
        records = [
            {
                "id": f"municipality:{index}",
                "name": f"Town {index}",
                "category": "sidlo",
                "population": population,
                "cell": f"A{index}",
                "gps": {"latitude": 50.0, "longitude": 14.0},
            }
            for index, population in enumerate((100_000, 120_000, 99_999), start=1)
        ]
        records.extend(
            {
                "id": f"airport:{icao}",
                "name": f"Airport {icao}",
                "category": "airport",
                "airport_type": "aerodrome",
                "airport_categories": {"international": True},
                "icao": icao,
                "cell": "M",
                "gps": {"latitude": 50.1, "longitude": 14.1},
            }
            for icao in ("LKAA", "LKBB")
        )
        records.append(
            {
                **records[-1],
                "id": "airport:LKHP",
                "icao": "LKHP",
                "airport_type": "heliport",
            }
        )
        locations = {
            "population_year": 2025,
            "grid": {"edge_length_km": 41.5},
            "records": records,
        }

        first_student, first_key = build_exam_documents(
            locations,
            difficulty=1,
            population_minimum=100_000,
            airport_category="international",
            airport_count=1,
            seed=42,
        )
        second_student, second_key = build_exam_documents(
            locations,
            difficulty=1,
            population_minimum=100_000,
            airport_category="international",
            airport_count=1,
            seed=42,
        )

        self.assertEqual(first_student, second_student)
        self.assertEqual(first_key, second_key)
        self.assertEqual(first_student["item_count"], 3)
        self.assertEqual(
            {question["location_id"] for question in first_student["questions"]},
            {"municipality:1", "municipality:2", "airport:LKAA"},
        )
        question_labels = {
            question["location_id"]: question["name"]
            for question in first_student["questions"]
        }
        self.assertEqual(question_labels["airport:LKAA"], "LKAA")
        self.assertEqual(question_labels["municipality:1"], "Town 1")
        self.assertEqual(
            {answer["cell"] for answer in first_key["answers"]},
            {"A1", "A2", "M"},
        )
        self.assertNotIn("answers", first_student)

    def test_rejects_ineligible_explicit_airport(self) -> None:
        with self.assertRaisesRegex(ValueError, "not eligible"):
            build_exam_documents(
                {
                    "records": [
                        {
                            "id": "municipality:1",
                            "name": "Town",
                            "category": "sidlo",
                            "population": 100_000,
                            "cell": "A",
                            "gps": {"latitude": 50.0, "longitude": 14.0},
                        }
                    ]
                },
                difficulty=1,
                population_minimum=100_000,
                airport_category="international",
                airport_count=1,
                seed=1,
                airport_icao_codes=["LKNO"],
            )

    def test_selects_highest_population_supplemental_settlements(self) -> None:
        towns = [
            {
                "id": f"municipality:{population}",
                "name": f"Town {population}",
                "category": "sidlo",
                "population": population,
                "cell": "A",
                "gps": {"latitude": 50.0, "longitude": 14.0},
            }
            for population in (100_000, 99_999, 90_000, 80_000, 74_999)
        ]

        student, _ = build_exam_documents(
            {"records": towns},
            difficulty=1,
            population_minimum=100_000,
            supplemental_population_minimum=75_000,
            supplemental_settlement_count=2,
            airport_category="international",
            airport_count=0,
            seed=1,
        )

        self.assertEqual(
            {question["location_id"] for question in student["questions"]},
            {
                "municipality:100000",
                "municipality:99999",
                "municipality:90000",
            },
        )


if __name__ == "__main__":
    unittest.main()
