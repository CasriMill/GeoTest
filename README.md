# GeoTest

GeoTest is a Python application for generating printable ATC training tests
based on a hexagonal grid fitted to a map of the Czech Republic.

## Planned test materials

- A student map with the hexagonal cells labeled by letters.
- A list of settlements for the student to locate by cell.
- An answer area for the student's confidence in each response: certain,
  probable, or guessed.
- Five difficulty levels and multiple test versions to reduce copying.
- A teacher map and scoring key for each version and difficulty level.

The app creates a blank outline map from the Czech Republic's OpenStreetMap
administrative boundary and provides an interactive tool for fitting a regular
hexagonal grid. SVG maps include OpenStreetMap attribution. Printable tests
and PDF generation are not implemented yet.

## Run

From the project directory, create and activate a virtual environment, then
install the package:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m geotest
```

To download the latest boundary and create the SVG preview:

```powershell
python -m geotest boundary
```

The map is written to `output/czechia_boundary.svg` by default. Use
`--output path\to\map.svg` to choose another location.

To create a preview of one parent cell and its seven children:

```powershell
python -m geotest grid
```

The preview is written to `output/czechia_hex_grid.svg` by default. The parent
is a regular hexagon fitted around the whole country; the seven equal child
hexagons form a touching center-and-neighbors grid inside it.

To preview the next division as well:

```powershell
python -m geotest grid3
```

This first builds the complete grid through the third level, then rotates and
translates that fixed grid as a whole relative to the country. It searches
parent scales from 1.0× to 1.5× in 0.1 steps and refines by 1% within ±5% of
the best coarse scale. At each rotation and scale it samples feasible
north-south and east-west translations, requires full country coverage, and
prefers layouts with no occupied cell having less than 10% of its area inside
Czechia. Among layouts with the same number of under-10% cells, it maximizes
the least-used cell's coverage and then average coverage before minimizing
cell count, allowing 24 cells if they materially use the boundary cells better.
Polygon intersection is exact. The SVG shows only cells intersecting
the country and highlights cells below the 10% threshold in orange. The
current geometry preview intentionally has no cell letters; those are reserved
for the final map. It is written to
`output/czechia_hex_grid_level3.svg`. The command also reports the winning
rotation and east/north offsets, occupied-cell count, and approximate edge
length and area of a third-level cell.

For manual fitting of a regular hexagonal tiling:

```powershell
python -m geotest gui
```

The GUI downloads the current OSM boundary and runs locally. Sliders control
hexagon edge length, east-west and north-south offsets, and rotation. The
statistics panel reports every hexagon intersecting Czechia, its share of
country area, cells with less than 10% of their area inside the country, and
whether the union of those cells fully covers the country. The target is at
most 27 occupied cells, but the GUI remains free to show larger counts while
exploring. This regular tiling is the current fitting method; `grid3` remains
the earlier hierarchical prototype.

The GUI loads the saved fit from `output/czechia_hex_grid_config.json` when it
starts. **Uložit nastavení** saves the current edge, offsets, and rotation;
**Vytvořit finální SVG** exports the fully covered map with deterministic
alphabetical cell labels to `output/czechia_hex_grid_final.svg`.

To reproduce the final SVG later from the saved settings:

```powershell
python -m geotest final
```

The command fetches the current OpenStreetMap boundary. Use `--settings` to
select another JSON preset and `--output` to change the SVG destination.
The checked-in initial preset uses a 41.5 km edge, 46.5° rotation, a -29 km
east offset, and a -10 km north offset.

## Locations data

Generate the JSON list of Czech municipalities with more than 2,000 residents
and AIP-listed aerodromes and heliports:

```powershell
python -m geotest locations
```

The default output is `data/locations.json`; `--output` selects another path
and `--year` selects a CSO reference year. The municipality population limit
is strictly greater than 2,000; all source rows are processed, but smaller
municipalities are omitted from the generated file. The file retains exact municipal
population alongside a derived threshold class, ICAO codes and AIP categories
for aviation locations, WGS84 GPS coordinates, and the A–Z grid cell.
Coordinates include provider and method metadata. Municipal-office points are
used where OpenStreetMap maps a matching `amenity=townhall`; otherwise the
municipality boundary centre is used and explicitly marked as a fallback.
Aerodrome points are matched first in OpenStreetMap and then in OurAirports.

Population figures and municipality identifiers come from the CSO DataStat
dataset `OBY01B01`. The AIP AD 1.3 index supplies ICAO codes and aviation
classification; its `G` general-aviation code is recorded as a sport candidate
and is broader than a definitive sports-aerodrome designation. Map coordinates
from OpenStreetMap are subject to the ODbL; each source and source element is
recorded in the data.

## Test

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```
