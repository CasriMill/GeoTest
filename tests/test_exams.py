import unittest

from geotest.exams import build_exam_documents


class ExamSetTests(unittest.TestCase):
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
