import unittest

from geotest.boundary import parse_boundary_rings, render_boundary_svg


BOUNDARY_XML = b"""\
<osm version="0.6">
  <node id="1" lon="0" lat="0"/>
  <node id="2" lon="2" lat="0"/>
  <node id="3" lon="2" lat="2"/>
  <node id="4" lon="0" lat="2"/>
  <node id="5" lon="0.5" lat="0.5"/>
  <node id="6" lon="1" lat="0.5"/>
  <node id="7" lon="1" lat="1"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/></way>
  <way id="11"><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
  <way id="12"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="5"/></way>
  <relation id="51684">
    <member type="way" ref="10" role="outer"/>
    <member type="way" ref="11" role="outer"/>
    <member type="way" ref="12" role="inner"/>
  </relation>
</osm>
"""


class BoundaryTests(unittest.TestCase):
    def test_parse_joins_outer_ways_and_preserves_inner_ring(self) -> None:
        rings = parse_boundary_rings(BOUNDARY_XML)

        self.assertEqual([role for role, _ in rings], ["outer", "inner"])
        self.assertEqual(len(rings[0][1]), 5)
        self.assertEqual(rings[0][1][0], rings[0][1][-1])
        self.assertEqual(rings[1][1][0], rings[1][1][-1])

    def test_render_adds_outline_and_openstreetmap_attribution(self) -> None:
        rings = parse_boundary_rings(BOUNDARY_XML)

        svg = render_boundary_svg(rings)

        self.assertIn('fill-rule="evenodd"', svg)
        self.assertIn("OpenStreetMap contributors", svg)
        self.assertIn("<path d=", svg)

    def test_parse_rejects_missing_relation(self) -> None:
        with self.assertRaisesRegex(ValueError, "is missing"):
            parse_boundary_rings(b'<osm><relation id="1"/></osm>')


if __name__ == "__main__":
    unittest.main()
