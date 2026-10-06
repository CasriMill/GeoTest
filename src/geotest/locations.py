from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
import csv
from html.parser import HTMLParser
import io
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from geotest.boundary import parse_boundary_rings
from geotest.final_map import (
    DEFAULT_SETTINGS_PATH,
    HexGridSettings,
    alphabetic_label,
    find_cell_label,
    load_settings,
)
from geotest.hexgrid import Ring
from geotest.tiling import GridAnalysis, analyze_hex_tiling, project_boundary_to_km


DEFAULT_LOCATIONS_PATH = Path("data/locations.json")
CSO_DATASET_CODE = "OBY01B01"
CSO_POPULATION_INDICATOR = "2406K"
CSO_MUNICIPALITY_DIMENSION = "UZ25"
CSO_YEAR_DIMENSION = "CasR"
CSO_CATALOG_URL = "https://data.csu.gov.cz/api/katalog/v1"
CSO_QUERY_URL = "https://data.csu.gov.cz/api/dotaz/v1/data/sady"
AIP_INDEX_URL = "https://aim.rlp.cz/eaip/html/eAIP/LK-AD-1.3-en-GB.html"
OURAIRPORTS_URL = (
    "https://raw.githubusercontent.com/davidmegginson/"
    "ourairports-data/main/airports.csv"
)
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_OVERPASS_FALLBACK_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OSM_CZECHIA_AREA_ID = 3_600_000_000 + 51_684
OSM_CZECHIA_BBOX = "48.5,12.0,51.1,18.9"
OVERPASS_CACHE_DIR = Path(".cache/geotest")
MINIMUM_MUNICIPALITY_POPULATION = 2_500
PRAHA_RUIAN_CODE = "554782"
PRAHA_FALLBACK_CENTRE = {
    "latitude": 50.0873677,
    "longitude": 14.4213250,
    "osm_element_id": 815041625,
}
PRAHA_FALLBACK_METHOD = "Mariánský sloup, Staroměstské náměstí (fallback)"
AIRPORT_COORDINATE_OVERRIDES = {
    "LKMR": {
        "latitude": 49.92277778,
        "longitude": 12.72472222,
        "provider": "Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Mari%C3%A1nsk%C3%A9_L%C3%A1zn%C4%9B_Airport",
        "method": "AIP ICAO match; user-provided DMS coordinates",
    },
}

_POPULATION_BANDS = (
    (500_000, "500000_plus"),
    (100_000, "100000_499999"),
    (50_000, "50000_99999"),
    (25_000, "25000_49999"),
    (5_000, "5000_24999"),
    (2_500, "2500_4999"),
)
_OFFICE_PREFIXES = (
    "magistrat hlavniho mesta",
    "magistrat mesta",
    "magistrat",
    "mestsky urad mesta",
    "mestsky urad",
    "mestska radnice",
    "mestysny urad",
    "obecni urad obce",
    "obecni urad",
    "radnice mesta",
    "radnice obce",
    "radnice",
    "urad mestske casti",
    "urad mestskeho obvodu",
)


class _AIPTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._skip_metadata = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []
            self._row.append(self._cell)
        elif tag == "span" and attributes.get("class") == "sdParams":
            self._skip_metadata = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._skip_metadata:
            self._skip_metadata = False
        elif tag == "td":
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(
                [" ".join(cell).strip() for cell in self._row]
            )
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._skip_metadata:
            self._cell.append(data)


def population_class(population: int) -> tuple[str, int | None]:
    for threshold, label in _POPULATION_BANDS:
        if population >= threshold:
            return label, threshold
    return "under_2500", None


def parse_population_csv(
    csv_text: str,
    minimum_population_inclusive: int | None = MINIMUM_MUNICIPALITY_POPULATION,
) -> list[dict[str, object]]:
    if (
        minimum_population_inclusive is not None
        and minimum_population_inclusive < 0
    ):
        raise ValueError("Minimum population threshold cannot be negative")
    rows = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    municipalities: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for row in rows:
        code = row.get("UZ25.OBEC", "").strip()
        name = row.get("Kraje a obce-Obec", "").strip()
        if not code or not name:
            continue
        if code in seen_codes:
            raise ValueError(f"CSO data repeats municipality code {code}")
        seen_codes.add(code)
        try:
            population_value = float(row["Hodnota"])
        except (KeyError, ValueError) as error:
            raise ValueError(
                f"CSO population for municipality {code} is invalid"
            ) from error
        if not population_value.is_integer() or population_value < 0:
            raise ValueError(
                f"CSO population for municipality {code} is not a nonnegative integer"
            )
        population = int(population_value)
        population_group, population_threshold = population_class(population)
        municipalities.append(
            {
                "id": f"municipality:{code}",
                "name": name,
                "category": "sidlo",
                "ruian_code": code,
                "region": row.get("Kraje a obce-Kraj", "").strip(),
                "region_code": row.get("UZ25.KRAJ", "").strip(),
                "population": population,
                "population_class": population_group,
                "population_class_threshold": population_threshold,
            }
        )
    if not municipalities:
        raise ValueError("CSO returned no municipality population records")
    if minimum_population_inclusive is None:
        return municipalities
    return [
        municipality
        for municipality in municipalities
        if municipality["population"] >= minimum_population_inclusive
    ]


def parse_aip_index(html_text: str) -> tuple[list[dict[str, str]], str]:
    parser = _AIPTableParser()
    parser.feed(html_text)
    parser.close()

    section = ""
    entries: list[dict[str, str]] = []
    for cells in parser.rows:
        row_text = " ".join(cells).upper()
        if "AERODROMES" in row_text:
            section = "aerodrome"
            continue
        if "HELIPORTS" in row_text:
            section = "heliport"
            continue
        if len(cells) < 7 or not re.fullmatch(r"LK[A-Z]{2}", cells[1]):
            continue
        if not section:
            raise ValueError("AIP aerodrome row is not under a known section")
        entries.append(
            {
                "name": cells[0],
                "icao": cells[1],
                "airport_type": section,
                "aip_traffic": cells[2],
                "aip_flight_rules": cells[3],
                "aip_ad_code": cells[4],
                "aip_use_code": cells[5],
                "aip_remarks": cells[6],
            }
        )

    edition_match = re.search(
        r'name="EM\.effectiveDateStart"\s+content="([^"]+)"',
        html_text,
    )
    effective_date = edition_match.group(1) if edition_match else ""
    if not entries:
        raise ValueError("AIP index did not contain any ICAO-coded locations")
    if len({entry["icao"] for entry in entries}) != len(entries):
        raise ValueError("AIP index contains duplicate ICAO identifiers")
    return entries, effective_date


def _request_json(url: str, payload: dict[str, object] | None = None) -> object:
    headers = {
        "Accept": "application/json",
        "Accept-Language": "cs",
        "User-Agent": "GeoTest/0.1 (Czech Republic map data)",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers)
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/csv,text/html,*/*",
            "Accept-Language": "cs",
            "User-Agent": "GeoTest/0.1 (Czech Republic map data)",
        },
    )
    with urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8-sig")


def _fetch_population_csv(year: int | None) -> tuple[str, int, str]:
    dataset = _request_json(f"{CSO_CATALOG_URL}/sady/{CSO_DATASET_CODE}")
    if not isinstance(dataset, dict):
        raise ValueError("CSO dataset metadata has an unexpected format")
    version = str(dataset["verze"])
    dimensions = {
        item["kod"]: item for item in dataset.get("variantyDimenze", [])
    }
    if CSO_MUNICIPALITY_DIMENSION not in dimensions:
        raise ValueError("CSO population dataset no longer includes UZ25")
    if CSO_YEAR_DIMENSION not in dimensions:
        raise ValueError("CSO population dataset no longer includes CasR")

    selected_year = year
    if selected_year is None:
        time_dimension = dimensions[CSO_YEAR_DIMENSION]
        periods = _request_json(
            f"{CSO_CATALOG_URL}/dimenze/{CSO_YEAR_DIMENSION}/polozky?"
            + urlencode({"verze": time_dimension["verze"]})
        )
        available_years = [
            int(item["kod"])
            for item in periods
            if item.get("kodUrovne") == "CAS_R"
            and str(item["kod"]).isdigit()
        ]
        selected_year = min(max(available_years), datetime.now(UTC).year - 1)

    payload: dict[str, object] = {
        "sloupce": [
            {
                "kodDimenze": "IndicatorType",
                "filtr": [{"zobrazitPolozky": [CSO_POPULATION_INDICATOR]}],
            },
            {
                "kodDimenze": CSO_YEAR_DIMENSION,
                "filtr": [{"zobrazitPolozky": [str(selected_year)]}],
            },
            {"kodDimenze": CSO_MUNICIPALITY_DIMENSION, "filtr": []},
        ],
        "radky": [],
        "filtryTabulky": [],
    }
    url = (
        f"{CSO_QUERY_URL}/{CSO_DATASET_CODE}/vlastni?"
        + urlencode(
            {
                "verzeSady": version,
                "format": "CSV",
                "kodZvlast": "true",
            }
        )
    )
    csv_text = _request_text_with_json_body(url, payload)
    return csv_text, selected_year, url


def _request_text_with_json_body(
    url: str,
    payload: dict[str, object],
) -> str:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "text/csv",
            "Accept-Language": "cs",
            "Content-Type": "application/json",
            "User-Agent": "GeoTest/0.1 (Czech Republic map data)",
        },
    )
    with urlopen(request, timeout=180) as response:
        return response.read().decode("utf-8-sig")


def _fetch_overpass(query: str) -> list[dict[str, object]]:
    cache_name = sha256(query.encode("utf-8")).hexdigest()
    cache_path = OVERPASS_CACHE_DIR / f"overpass-{cache_name}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, list) and all(
            isinstance(element, dict) for element in cached
        ):
            return cached
        raise ValueError(f"Invalid cached Overpass response in {cache_path}")

    errors: list[str] = []
    for endpoint in (OSM_OVERPASS_URL, *OSM_OVERPASS_FALLBACK_URLS):
        url = endpoint + "?" + urlencode({"data": query})
        try:
            result = _request_json(url)
        except (OSError, TimeoutError) as error:
            errors.append(f"{endpoint}: {error}")
            continue
        if isinstance(result, dict) and isinstance(result.get("elements"), list):
            elements = result["elements"]
            if not all(isinstance(element, dict) for element in elements):
                raise ValueError("OpenStreetMap Overpass returned invalid elements")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = cache_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(elements, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary_path.replace(cache_path)
            return elements
        errors.append(f"{endpoint}: unexpected response format")
    raise RuntimeError(
        "Every configured OpenStreetMap Overpass endpoint failed: "
        + " | ".join(errors)
    )


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _municipality_aliases(element: dict[str, object]) -> set[str]:
    tags = element.get("tags", {})
    aliases = {
        _fold(value)
        for key in ("name", "official_name", "addr:city", "alt_name")
        if isinstance((value := tags.get(key)), str) and value.strip()
    }
    for name in tuple(aliases):
        for prefix in _OFFICE_PREFIXES:
            if name.startswith(prefix + " "):
                aliases.add(name[len(prefix) + 1 :])
    return aliases


def _distance_squared(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def _osm_position(element: dict[str, object]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _municipality_centres(
    municipalities: list[dict[str, object]],
    boundary_elements: list[dict[str, object]],
) -> dict[str, tuple[tuple[float, float], dict[str, object]]]:
    municipalities_by_code = {
        str(municipality["ruian_code"]): municipality
        for municipality in municipalities
    }
    centres: dict[str, tuple[tuple[float, float], dict[str, object]]] = {}
    name_candidates: dict[str, list[dict[str, object]]] = defaultdict(list)
    for element in boundary_elements:
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            continue
        position = _osm_position(element)
        if position is None:
            continue
        ref = str(tags.get("ref", ""))
        code_match = re.search(r"(\d{6})$", ref)
        code = code_match.group(1) if code_match else ""
        if code in municipalities_by_code:
            if code in centres:
                raise ValueError(f"OpenStreetMap repeats municipality code {code}")
            centres[code] = (position, element)
        name = tags.get("name")
        if isinstance(name, str):
            name_candidates[_fold(name)].append(element)

    for municipality in municipalities:
        code = str(municipality["ruian_code"])
        if code in centres:
            continue
        if code == PRAHA_RUIAN_CODE:
            centres[code] = (
                (
                    PRAHA_FALLBACK_CENTRE["latitude"],
                    PRAHA_FALLBACK_CENTRE["longitude"],
                ),
                {
                    "type": "way",
                    "id": PRAHA_FALLBACK_CENTRE["osm_element_id"],
                    "coordinate_method": PRAHA_FALLBACK_METHOD,
                },
            )
            continue
        name = _fold(str(municipality["name"]))
        candidates = name_candidates.get(name, [])
        if len(candidates) == 1:
            position = _osm_position(candidates[0])
            if position is not None:
                centres[code] = (position, candidates[0])
    missing = sorted(set(municipalities_by_code) - set(centres))
    if missing:
        raise ValueError(
            "OpenStreetMap has no administrative centre for municipality "
            + ", ".join(missing[:12])
        )
    return centres


def _municipal_offices(
    office_elements: list[dict[str, object]],
    municipalities: list[dict[str, object]],
    centres: dict[str, tuple[tuple[float, float], dict[str, object]]],
) -> dict[str, tuple[tuple[float, float], dict[str, object]]]:
    aliases_to_codes: dict[str, set[str]] = defaultdict(set)
    for municipality in municipalities:
        code = str(municipality["ruian_code"])
        aliases_to_codes[_fold(str(municipality["name"]))].add(code)

    candidates: dict[
        str,
        list[tuple[int, float, tuple[float, float], dict[str, object]]],
    ] = defaultdict(list)
    for element in office_elements:
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            continue
        position = _osm_position(element)
        if position is None:
            continue
        alias_codes: set[str] = set()
        alias_score = 0
        for key in ("addr:city", "name", "official_name", "alt_name"):
            value = tags.get(key)
            if not isinstance(value, str):
                continue
            for alias in _municipality_aliases({"tags": {key: value}}):
                matches = aliases_to_codes.get(alias, set())
                if matches:
                    alias_codes.update(matches)
                    alias_score = max(alias_score, 2 if key == "name" else 1)
        for code in alias_codes:
            centre = centres[code][0]
            candidates[code].append(
                (
                    alias_score,
                    _distance_squared(position, centre),
                    position,
                    element,
                )
            )
    return {
        code: (position, element)
        for code, matches in candidates.items()
        for _, _, position, element in [max(matches, key=lambda item: (item[0], -item[1]))]
    }


def _airport_categories(entry: dict[str, str]) -> dict[str, bool]:
    traffic = {
        item
        for item in re.split(r"[^A-Z]+", entry["aip_traffic"].upper())
        if item
    }
    use_codes = {
        item
        for item in re.split(r"[^A-Z]+", entry["aip_use_code"].upper())
        if item
    }
    general_aviation = "G" in use_codes
    return {
        "international": "INTL" in traffic,
        "civil": bool(traffic.intersection({"INTL", "NTL"}) or general_aviation),
        "sport": general_aviation,
        "military": "MIL" in traffic or "M" in use_codes,
    }


def _eligible_airport_entries(
    entries: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        entry
        for entry in entries
        if entry["airport_type"] == "aerodrome"
        and any(_airport_categories(entry).values())
    ]


def _airport_name_score(first: str, second: str) -> int:
    left, right = _fold(first), _fold(second)
    if left == right:
        return 3
    qualifiers = (
        " airport",
        " aerodrome",
        " letiste",
        " aeroklub",
        " aeroclub",
    )
    for qualifier in qualifiers:
        if left.endswith(qualifier):
            left = left[: -len(qualifier)].strip()
        if right.endswith(qualifier):
            right = right[: -len(qualifier)].strip()
    if left == right:
        return 2
    if left and right and (left.endswith(" " + right) or right.endswith(" " + left)):
        return 1
    return 0


def _airport_coordinates(
    entries: list[dict[str, str]],
    osm_elements: list[dict[str, object]],
    ourairports_rows: list[dict[str, str]],
) -> dict[str, tuple[tuple[float, float], dict[str, object]]]:
    by_icao: dict[str, list[dict[str, object]]] = defaultdict(list)
    for element in osm_elements:
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            continue
        for key in ("icao", "ref:icao", "ref"):
            value = str(tags.get(key, "")).upper().strip()
            if re.fullmatch(r"LK[A-Z]{2}", value):
                by_icao[value].append(element)

    ourairports_by_code: dict[str, dict[str, str]] = {}
    for row in ourairports_rows:
        if row.get("iso_country") != "CZ":
            continue
        for key in ("gps_code", "ident", "local_code"):
            code = row.get(key, "").upper().strip()
            if re.fullmatch(r"LK[A-Z]{2}", code):
                ourairports_by_code.setdefault(code, row)

    coordinates: dict[str, tuple[tuple[float, float], dict[str, object]]] = {}
    for entry in entries:
        code = entry["icao"]
        candidates = by_icao.get(code, [])
        if candidates:
            named_candidates = [
                (element, _airport_name_score(entry["name"], str(element.get("tags", {}).get("name", ""))))
                for element in candidates
            ]
            element, _ = max(
                named_candidates,
                key=lambda candidate: (
                    candidate[1],
                    candidate[0].get("type") == "node",
                    -int(candidate[0].get("id", 0)),
                ),
            )
            position = _osm_position(element)
            if position is not None:
                coordinates[code] = (
                    position,
                    {
                        "provider": "OpenStreetMap",
                        "element_type": element.get("type"),
                        "element_id": element.get("id"),
                        "method": "ICAO/ref match",
                    },
                )
                continue

        row = ourairports_by_code.get(code)
        if row is not None:
            try:
                position = (float(row["latitude_deg"]), float(row["longitude_deg"]))
            except (KeyError, ValueError):
                position = None
            if position is not None:
                coordinates[code] = (
                    position,
                    {
                        "provider": "OurAirports",
                        "ident": row.get("ident"),
                        "method": "GPS/ICAO identifier match",
                    },
                )
                continue

        named_candidates = []
        for element in osm_elements:
            tags = element.get("tags", {})
            if not isinstance(tags, dict):
                continue
            name = str(tags.get("name", ""))
            score = _airport_name_score(entry["name"], name)
            position = _osm_position(element)
            if score and position is not None:
                named_candidates.append((score, position, element))
        if named_candidates:
            score, position, element = max(
                named_candidates,
                key=lambda candidate: (
                    candidate[0],
                    candidate[2].get("type") == "node",
                ),
            )
            coordinates[code] = (
                position,
                {
                    "provider": "OpenStreetMap",
                    "element_type": element.get("type"),
                    "element_id": element.get("id"),
                    "method": f"name match (score {score})",
                },
            )

        override = AIRPORT_COORDINATE_OVERRIDES.get(code)
        if override is not None:
            coordinates[code] = (
                (override["latitude"], override["longitude"]),
                {
                    "provider": override["provider"],
                    "url": override["url"],
                    "method": override["method"],
                },
            )

    missing = sorted({entry["icao"] for entry in entries} - set(coordinates))
    if missing:
        raise ValueError(
            "No GPS coordinates found for AIP aerodromes: " + ", ".join(missing)
        )
    return coordinates


def _parse_ourairports_csv(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))


def _ourairports_icao_codes(rows: list[dict[str, str]]) -> set[str]:
    codes: set[str] = set()
    for row in rows:
        if row.get("iso_country") != "CZ":
            continue
        for key in ("gps_code", "ident", "local_code"):
            code = row.get(key, "").upper().strip()
            if re.fullmatch(r"LK[A-Z]{2}", code):
                codes.add(code)
    return codes


def _airport_coordinate_query(
    entries: list[dict[str, str]],
    ourairports_rows: list[dict[str, str]],
) -> str | None:
    missing_codes = sorted(
        {entry["icao"] for entry in entries} - _ourairports_icao_codes(ourairports_rows)
    )
    if not missing_codes:
        return None
    code_pattern = "|".join(missing_codes)
    return (
        "[out:json][timeout:45];"
        + "".join(
            f'nwr["{key}"~"^({code_pattern})$"]({OSM_CZECHIA_BBOX});'
            for key in ("icao", "ref:icao", "ref")
        )
        + "out center tags;"
    )


def build_location_document(
    population_csv: str,
    boundary_elements: list[dict[str, object]],
    office_elements: list[dict[str, object]],
    aip_html: str,
    aeroway_elements: list[dict[str, object]],
    ourairports_csv: str,
    boundary_rings: list[Ring],
    settings: HexGridSettings,
    population_year: int,
    generated_at: str | None = None,
) -> dict[str, object]:
    source_municipalities = parse_population_csv(
        population_csv,
        minimum_population_inclusive=None,
    )
    municipalities = [
        municipality
        for municipality in source_municipalities
        if municipality["population"] >= MINIMUM_MUNICIPALITY_POPULATION
    ]
    if not municipalities:
        raise ValueError(
            "CSO population data has no municipalities with at least "
            f"{MINIMUM_MUNICIPALITY_POPULATION} residents"
        )
    centres = _municipality_centres(municipalities, boundary_elements)
    offices = _municipal_offices(office_elements, municipalities, centres)

    aip_entries, aip_effective_date = parse_aip_index(aip_html)
    aip_entries = _eligible_airport_entries(aip_entries)
    if not aip_entries:
        raise ValueError(
            "The AIP index has no aerodromes in the selected categories"
        )
    ourairports_rows = _parse_ourairports_csv(ourairports_csv)
    coordinate_query = _airport_coordinate_query(aip_entries, ourairports_rows)
    if coordinate_query is not None:
        aeroway_elements.extend(_fetch_overpass(coordinate_query))
    airport_coordinates = _airport_coordinates(
        aip_entries,
        aeroway_elements,
        ourairports_rows,
    )

    country = project_boundary_to_km(boundary_rings)
    analysis = analyze_hex_tiling(
        country,
        settings.edge_length_km,
        settings.offset_east_km,
        settings.offset_north_km,
        settings.rotation_degrees,
    )
    if not analysis.fully_covered:
        raise ValueError("The configured hex grid does not cover the whole country")

    records: list[dict[str, object]] = []
    office_count = 0
    for municipality in municipalities:
        code = str(municipality["ruian_code"])
        fallback_position, boundary_element = centres[code]
        office = offices.get(code)
        if office is None:
            position = fallback_position
            coordinate_source = {
                "provider": "OpenStreetMap",
                "element_type": boundary_element.get("type"),
                "element_id": boundary_element.get("id"),
                "method": boundary_element.get(
                    "coordinate_method",
                    "administrative boundary centre (fallback; not the town hall)",
                ),
            }
        else:
            position, element = office
            office_count += 1
            coordinate_source = {
                "provider": "OpenStreetMap",
                "element_type": element.get("type"),
                "element_id": element.get("id"),
                "method": "amenity=townhall feature",
            }
        record = {
            **municipality,
            "gps": {"latitude": position[0], "longitude": position[1]},
            "cell": find_cell_label(analysis, (position[1], position[0]), boundary_rings),
            "coordinate_source": coordinate_source,
        }
        records.append(record)

    for entry in aip_entries:
        (latitude, longitude), coordinate_source = airport_coordinates[entry["icao"]]
        records.append(
            {
                "id": f"airport:{entry['icao']}",
                "name": entry["name"],
                "category": "airport",
                "population": None,
                "population_class": None,
                "population_class_threshold": None,
                "icao": entry["icao"],
                "airport_type": entry["airport_type"],
                "airport_categories": _airport_categories(entry),
                "aip": {
                    "traffic": entry["aip_traffic"],
                    "flight_rules": entry["aip_flight_rules"],
                    "ad_code": entry["aip_ad_code"],
                    "use_code": entry["aip_use_code"],
                    "remarks": entry["aip_remarks"],
                },
                "gps": {"latitude": latitude, "longitude": longitude},
                "cell": find_cell_label(
                    analysis,
                    (longitude, latitude),
                    boundary_rings,
                ),
                "coordinate_source": coordinate_source,
            }
        )

    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "population_year": population_year,
        "municipality_population_filter": {
            "operator": ">=",
            "minimum_population": MINIMUM_MUNICIPALITY_POPULATION,
        },
        "airport_filter": {
            "airport_types": ["aerodrome"],
            "included_categories": [
                "international",
                "civil",
                "sport",
                "military",
            ],
            "operator": "any",
        },
        "grid": {
            "edge_length_km": settings.edge_length_km,
            "offset_east_km": settings.offset_east_km,
            "offset_north_km": settings.offset_north_km,
            "rotation_degrees": settings.rotation_degrees,
            "cell_labels": [
                alphabetic_label(index) for index in range(len(analysis.cells))
            ],
            "fully_covered": analysis.fully_covered,
        },
        "counts": {
            "municipalities": len(municipalities),
            "source_municipalities": len(source_municipalities),
            "municipalities_excluded_by_population": (
                len(source_municipalities) - len(municipalities)
            ),
            "aip_entries_in_source_index": len(parse_aip_index(aip_html)[0]),
            "municipalities_using_townhall_points": office_count,
            "municipalities_using_boundary_centres": (
                len(municipalities) - office_count
            ),
            "aip_aerodromes": len(aip_entries),
            "total_records": len(records),
        },
        "classification_notes": {
            "population_class": (
                "Highest configured minimum threshold met; exact population is retained."
            ),
            "airport_sport": (
                "Derived from the AIP G (general aviation) use code; this is broader "
                "than a confirmed sports-aerodrome designation."
            ),
        },
        "sources": [
            {
                "name": "Český statistický úřad — DataStat",
                "dataset_code": CSO_DATASET_CODE,
                "indicator_code": CSO_POPULATION_INDICATOR,
                "indicator": "Počet obyvatel k 31. 12.",
                "year": population_year,
                "url": (
                    f"{CSO_QUERY_URL}/{CSO_DATASET_CODE}/vlastni"
                ),
            },
            {
                "name": "ŘLP ČR — AIP Czech Republic, AD 1.3",
                "effective_date": aip_effective_date,
                "url": AIP_INDEX_URL,
                "used_for": "ICAO identifiers and source airport categories",
            },
            {
                "name": "OpenStreetMap contributors",
                "url": "https://www.openstreetmap.org/",
                "license": "Open Database License (ODbL)",
                "used_for": (
                    "Municipality-office or administrative-centre coordinates; "
                    "aerodrome coordinates when directly mapped."
                ),
            },
            {
                "name": "OurAirports",
                "url": OURAIRPORTS_URL,
                "used_for": "Aerodrome GPS coordinates when not matched in OpenStreetMap.",
            },
            {
                "name": "Wikipedia — Mariánské Lázně Airport",
                "url": AIRPORT_COORDINATE_OVERRIDES["LKMR"]["url"],
                "used_for": "User-provided coordinates for LKMR.",
            },
        ],
        "records": records,
    }


def build_location_dataset(year: int | None = None) -> dict[str, object]:
    population_csv, selected_year, _ = _fetch_population_csv(year)
    overpass_header = "[out:json][timeout:60];"
    area = f"area({OSM_CZECHIA_AREA_ID})->.cz;"
    boundary_elements = _fetch_overpass(
        overpass_header
        + area
        + 'relation["boundary"="administrative"]["admin_level"="8"](area.cz);'
        + "out tags center;"
    )
    office_elements = _fetch_overpass(
        overpass_header + area + 'node["amenity"="townhall"](area.cz);out tags;'
    )
    aip_html = _request_text(AIP_INDEX_URL)
    ourairports_csv = _request_text(OURAIRPORTS_URL)
    aip_entries, _ = parse_aip_index(aip_html)
    aip_entries = _eligible_airport_entries(aip_entries)
    if not aip_entries:
        raise ValueError(
            "The AIP index has no aerodromes in the selected categories"
        )
    ourairports_rows = _parse_ourairports_csv(ourairports_csv)
    coordinate_query = _airport_coordinate_query(aip_entries, ourairports_rows)
    aeroway_elements = (
        _fetch_overpass(coordinate_query)
        if coordinate_query is not None
        else []
    )
    from geotest.boundary import fetch_boundary_data

    boundary_rings = parse_boundary_rings(fetch_boundary_data())
    settings = load_settings(DEFAULT_SETTINGS_PATH)
    return build_location_document(
        population_csv=population_csv,
        boundary_elements=boundary_elements,
        office_elements=office_elements,
        aip_html=aip_html,
        aeroway_elements=aeroway_elements,
        ourairports_csv=ourairports_csv,
        boundary_rings=boundary_rings,
        settings=settings,
        population_year=selected_year,
    )


def create_location_json(
    output_path: Path = DEFAULT_LOCATIONS_PATH,
    year: int | None = None,
) -> tuple[Path, dict[str, object]]:
    document = build_location_dataset(year)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output_path, document
