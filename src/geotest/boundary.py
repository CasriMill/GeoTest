from collections.abc import Sequence
from math import cos, radians
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


OSM_RELATION_ID = "51684"
OSM_RELATION_URL = (
    f"https://www.openstreetmap.org/api/0.6/relation/{OSM_RELATION_ID}/full"
)
OSM_ATTRIBUTION = (
    "© OpenStreetMap contributors · "
    f"https://www.openstreetmap.org/relation/{OSM_RELATION_ID} · ODbL"
)


def fetch_boundary_data() -> bytes:
    request = Request(
        OSM_RELATION_URL,
        headers={"User-Agent": "GeoTest/0.1 (Czech Republic boundary map)"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read()


def parse_boundary_rings(xml_data: bytes) -> list[tuple[str, list[tuple[float, float]]]]:
    root = ET.fromstring(xml_data)
    relation = next(
        (
            element
            for element in root.findall("relation")
            if element.get("id") == OSM_RELATION_ID
        ),
        None,
    )
    if relation is None:
        raise ValueError(f"OSM relation {OSM_RELATION_ID} is missing from the response")

    nodes = {
        node.get("id"): (float(node.get("lon", "")), float(node.get("lat", "")))
        for node in root.findall("node")
        if node.get("id") is not None
    }
    ways = {
        way.get("id"): tuple(ref.get("ref", "") for ref in way.findall("nd"))
        for way in root.findall("way")
        if way.get("id") is not None
    }
    member_ways = [
        (member.get("role", ""), ways.get(member.get("ref", ""), ()))
        for member in relation.findall("member")
        if member.get("type") == "way"
        and member.get("role") in ("outer", "inner")
    ]
    if not member_ways:
        raise ValueError(f"OSM relation {OSM_RELATION_ID} has no boundary ways")

    rings: list[tuple[str, list[tuple[float, float]]]] = []
    for role in ("outer", "inner"):
        segments = [
            list(refs) for member_role, refs in member_ways if member_role == role
        ]
        while segments:
            refs = segments.pop()
            while refs[-1] != refs[0]:
                for index, segment in enumerate(segments):
                    if segment[0] == refs[-1]:
                        refs.extend(segment[1:])
                    elif segment[-1] == refs[-1]:
                        refs.extend(reversed(segment[:-1]))
                    elif segment[-1] == refs[0]:
                        refs = segment[:-1] + refs
                    elif segment[0] == refs[0]:
                        refs = list(reversed(segment[1:])) + refs
                    else:
                        continue
                    segments.pop(index)
                    break
                else:
                    raise ValueError(
                        f"OSM relation {OSM_RELATION_ID} contains an incomplete "
                        f"{role} boundary ring"
                    )

            try:
                coordinates = [nodes[node_ref] for node_ref in refs]
            except KeyError as error:
                raise ValueError(
                    f"OSM boundary references missing node {error.args[0]}"
                ) from error
            rings.append((role, coordinates))

    if not any(role == "outer" for role, _ in rings):
        raise ValueError(f"OSM relation {OSM_RELATION_ID} has no outer boundary")
    return rings


def render_boundary_svg(
    rings: Sequence[tuple[str, Sequence[tuple[float, float]]]],
    width: int = 1000,
    height: int = 800,
    overlays: Sequence[
        tuple[Sequence[tuple[float, float]], str, str | None]
    ] = (),
    labels: Sequence[tuple[tuple[float, float], str]] = (),
    title: str = "Czech Republic — blank outline map",
    description: str | None = None,
) -> str:
    points = [point for _, ring in rings for point in ring]
    if not points:
        raise ValueError("Cannot render an empty boundary")

    center_lon = (min(lon for lon, _ in points) + max(lon for lon, _ in points)) / 2
    center_lat = (min(lat for _, lat in points) + max(lat for _, lat in points)) / 2
    x_scale = cos(radians(center_lat))
    project = lambda point: (
        (point[0] - center_lon) * x_scale,
        point[1] - center_lat,
    )
    projected = [
        ((lon - center_lon) * x_scale, lat - center_lat)
        for lon, lat in points
    ]
    projected_overlays = [
        ([(project(point)) for point in polygon], stroke, fill)
        for polygon, stroke, fill in overlays
    ]
    projected_labels = [(project(point), label) for point, label in labels]
    all_projected = projected + [
        point
        for polygon, _, _ in projected_overlays
        for point in polygon
    ] + [point for point, _ in projected_labels]
    min_x = min(x for x, _ in all_projected)
    max_x = max(x for x, _ in all_projected)
    min_y = min(y for _, y in all_projected)
    max_y = max(y for _, y in all_projected)

    padding = 32
    map_height = height - 56
    scale = min(
        (width - 2 * padding) / (max_x - min_x),
        (map_height - 2 * padding) / (max_y - min_y),
    )

    paths: list[str] = []
    point_index = 0
    for _, ring in rings:
        path_points = []
        for _ in ring:
            x, y = projected[point_index]
            point_index += 1
            path_points.append((x, y))
        paths.append(_svg_path(path_points, min_x, max_y, padding, scale))
    overlay_paths = []
    for polygon, stroke, fill in projected_overlays:
        fill_attribute = f' fill="{fill}"' if fill is not None else ' fill="none"'
        overlay_paths.append(
            f'<path d="{_svg_path(polygon, min_x, max_y, padding, scale)}"'
            f'{fill_attribute} stroke="{stroke}" stroke-width="2" '
            'stroke-linejoin="round"/>'
        )
    label_elements = []
    for (x, y), label in projected_labels:
        svg_x = padding + (x - min_x) * scale
        svg_y = padding + (max_y - y) * scale
        label_elements.append(
            f'<text x="{svg_x:.2f}" y="{svg_y:.2f}" '
            'text-anchor="middle" dominant-baseline="central" '
            'font-family="sans-serif" font-size="16" font-weight="bold" '
            'fill="#111" stroke="white" stroke-width="3" '
            f'paint-order="stroke">{label}</text>'
        )
    description = description or (
        f"Administrative boundary from OpenStreetMap relation {OSM_RELATION_ID}."
    )
    boundary_path = " ".join(paths)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">
  <title id="title">{title}</title>
  <desc id="description">{description}</desc>
  <rect width="100%" height="100%" fill="white"/>
  <path d="{boundary_path}" fill="#f8f8f8" fill-rule="evenodd"/>
  {' '.join(overlay_paths)}
  {' '.join(label_elements)}
  <path d="{boundary_path}" fill="none" fill-rule="evenodd" stroke="#202020" stroke-width="1.6" stroke-linejoin="round"/>
  <text x="{padding}" y="{height - 16}" font-family="sans-serif" font-size="11" fill="#444">{OSM_ATTRIBUTION}</text>
</svg>
"""


def _svg_path(
    points: Sequence[tuple[float, float]],
    min_x: float,
    max_y: float,
    padding: int,
    scale: float,
) -> str:
    path_points = [
        (padding + (x - min_x) * scale, padding + (max_y - y) * scale)
        for x, y in points
    ]
    commands = " ".join(
        f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}"
        for index, (x, y) in enumerate(path_points)
    )
    return f"{commands} Z"


def create_boundary_map(output_path: Path) -> Path:
    rings = parse_boundary_rings(fetch_boundary_data())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_boundary_svg(rings), encoding="utf-8")
    return output_path
