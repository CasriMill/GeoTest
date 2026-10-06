import unittest

from geotest.locations import (
    _airport_categories,
    parse_aip_index,
    parse_population_csv,
    population_class,
)


AIP_HTML = """\
<html>
  <head><meta name="EM.effectiveDateStart" content="2026-10-01"/></head>
  <body><table>
    <tr><td colspan="7"><strong>AERODROMES</strong></td></tr>
    <tr>
      <td><span class="SD">Benešov</span><span class="sdParams">hidden</span></td>
      <td><span class="SD">LKBE</span><span class="sdParams">hidden</span></td>
      <td>INTL-NTL</td><td>VFR</td><td>1B</td><td>G</td><td>VFR manual</td>
    </tr>
    <tr><td colspan="7"><strong>HELIPORTS</strong></td></tr>
    <tr>
      <td><span class="SD">Praha Motol</span><span class="sdParams">hidden</span></td>
      <td><span class="SD">LKPH</span><span class="sdParams">hidden</span></td>
      <td>NTL</td><td>VFR</td><td></td><td>HEMS</td><td></td>
    </tr>
  </table></body>
</html>
"""


class LocationDataTests(unittest.TestCase):
    def test_population_csv_excludes_values_at_or_below_two_thousand(self) -> None:
        csv_text = """\
"UZ25.OBEC","Kraje a obce-Obec","Kraje a obce-Kraj","UZ25.KRAJ","Hodnota"
"554782","Praha","Hlavní město Praha","CZ010","1407084.0"
"553433","Babylon","Plzeňský kraj","CZ032","2000.0"
"553434","Bdeněves","Plzeňský kraj","CZ032","2001.0"
"""

        records = parse_population_csv(csv_text)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["population"], 1_407_084)
        self.assertEqual(records[0]["population_class"], "500000_plus")
        self.assertEqual(records[1]["population"], 2_001)
        self.assertEqual(records[1]["population_class"], "under_5000")
        self.assertEqual(records[0]["ruian_code"], "554782")

    def test_population_csv_can_return_source_rows_for_filtering(self) -> None:
        csv_text = """\
"UZ25.OBEC","Kraje a obce-Obec","Kraje a obce-Kraj","UZ25.KRAJ","Hodnota"
"553433","Babylon","Plzeňský kraj","CZ032","2000.0"
"""

        records = parse_population_csv(
            csv_text,
            minimum_population_exclusive=None,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["population"], 2_000)

    def test_population_class_uses_the_highest_threshold_met(self) -> None:
        self.assertEqual(population_class(5_000), ("5000_24999", 5_000))
        self.assertEqual(population_class(25_000), ("25000_49999", 25_000))
        self.assertEqual(population_class(50_000), ("50000_99999", 50_000))
        self.assertEqual(population_class(100_000), ("100000_499999", 100_000))
        self.assertEqual(population_class(500_000), ("500000_plus", 500_000))

    def test_aip_parser_keeps_icao_type_and_effective_date(self) -> None:
        entries, effective_date = parse_aip_index(AIP_HTML)

        self.assertEqual(effective_date, "2026-10-01")
        self.assertEqual([entry["icao"] for entry in entries], ["LKBE", "LKPH"])
        self.assertEqual(
            [entry["airport_type"] for entry in entries],
            ["aerodrome", "heliport"],
        )
        self.assertEqual(entries[0]["name"], "Benešov")
        self.assertEqual(entries[0]["aip_use_code"], "G")

    def test_aip_categories_allow_multiple_simultaneous_flags(self) -> None:
        entry = {
            "aip_traffic": "INTL-NTL-MIL",
            "aip_use_code": "S, NS, M, G",
        }

        self.assertEqual(
            _airport_categories(entry),
            {
                "international": True,
                "civil": True,
                "sport": True,
                "military": True,
            },
        )

    def test_heliport_is_not_assumed_to_be_sport_or_international(self) -> None:
        entry = {"aip_traffic": "NTL", "aip_use_code": "HEMS"}

        self.assertEqual(
            _airport_categories(entry),
            {
                "international": False,
                "civil": True,
                "sport": False,
                "military": False,
            },
        )

    def test_population_csv_rejects_duplicate_municipality_codes(self) -> None:
        csv_text = """\
"UZ25.OBEC","Kraje a obce-Obec","Kraje a obce-Kraj","UZ25.KRAJ","Hodnota"
"554782","Praha","Hlavní město Praha","CZ010","1407084.0"
"554782","Praha","Hlavní město Praha","CZ010","1407084.0"
"""

        with self.assertRaisesRegex(ValueError, "repeats municipality code"):
            parse_population_csv(csv_text)


if __name__ == "__main__":
    unittest.main()
