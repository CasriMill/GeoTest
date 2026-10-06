import tempfile
import unittest
from pathlib import Path

from geotest.final_map import (
    HexGridSettings,
    alphabetic_label,
    find_cell_label,
    load_settings,
    ordered_hex_cells,
    render_final_map_svg,
    save_settings,
)
from geotest.boundary import parse_boundary_rings
from geotest.tiling import analyze_hex_tiling, project_boundary_to_km, unproject_km_point


BOUNDARY_XML = b"""\
<osm version="0.6">
  <node id="1" lon="0" lat="0"/>
  <node id="2" lon="0.2" lat="0"/>
  <node id="3" lon="0.2" lat="0.2"/>
  <node id="4" lon="0" lat="0.2"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
  <relation id="51684">
    <member type="way" ref="10" role="outer"/>
  </relation>
</osm>
"""


class FinalMapTests(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        settings = HexGridSettings()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grid.json"

            save_settings(settings, path)

            self.assertEqual(load_settings(path), settings)

    def test_alphabetic_labels_continue_after_z(self) -> None:
        self.assertEqual(
            [alphabetic_label(index) for index in (0, 25, 26, 27, 51, 52)],
            ["A", "Z", "AA", "AB", "AZ", "BA"],
        )

    def test_final_svg_has_labels_and_full_coverage(self) -> None:
        rings = parse_boundary_rings(BOUNDARY_XML)

        svg, analysis = render_final_map_svg(
            rings,
            HexGridSettings(
                edge_length_km=10,
                offset_east_km=0,
                offset_north_km=0,
                rotation_degrees=0,
            ),
        )

        self.assertTrue(analysis.fully_covered)
        self.assertIn("final labeled hex grid", svg)
        for index in range(len(analysis.cells)):
            self.assertIn(f">{alphabetic_label(index)}</text>", svg)

    def test_cell_lookup_matches_map_label_order(self) -> None:
        rings = parse_boundary_rings(BOUNDARY_XML)
        settings = HexGridSettings(
            edge_length_km=10,
            offset_east_km=0,
            offset_north_km=0,
            rotation_degrees=0,
        )
        country = project_boundary_to_km(rings)
        analysis = analyze_hex_tiling(country, settings.edge_length_km)
        expected_point = ordered_hex_cells(analysis)[0].polygon.centroid
        geographic_point = unproject_km_point(
            rings,
            (expected_point.x, expected_point.y),
        )

        self.assertEqual(find_cell_label(analysis, geographic_point, rings), "A")


if __name__ == "__main__":
    unittest.main()
