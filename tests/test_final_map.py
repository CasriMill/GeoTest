import tempfile
import unittest
from pathlib import Path

from geotest.final_map import (
    HexGridSettings,
    alphabetic_label,
    load_settings,
    render_final_map_svg,
    save_settings,
)
from geotest.boundary import parse_boundary_rings


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


if __name__ == "__main__":
    unittest.main()
