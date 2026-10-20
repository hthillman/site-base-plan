"""State Plane zone selection + transforms, nationwide.

Zones come from a bundled copy of the NAD83 State Plane zone boundaries
(data/spcs83_zones.geojson, from NGS SPCS83 via Esri), each mapped to a
foot-based coordinate system: US survey feet, or international feet where
the state legislated that (AZ, MI, MT, ND, OR, SC, UT). Most are
NAD83(2011) EPSG codes; Alaska, most of Hawaii, Missouri and Utah use the
equivalent Esri definitions because EPSG has no foot version there.

Washington keeps NAD83(HARN) (EPSG 2926 North / 2927 South), the frame the
WA statewide parcel layer and most WA county GIS use. The difference from
NAD83(2011) is centimetre-level, far below planning accuracy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

ZONES_FILE = Path(__file__).resolve().parent / "data" / "spcs83_zones.geojson"

WA_NORTH_COUNTIES = {
    "CHELAN", "CLALLAM", "DOUGLAS", "FERRY", "ISLAND", "JEFFERSON", "KING",
    "KITSAP", "LINCOLN", "OKANOGAN", "PEND OREILLE", "SAN JUAN", "SKAGIT",
    "SNOHOMISH", "SPOKANE", "STEVENS", "WHATCOM",
}
NORTH_COUNTIES = WA_NORTH_COUNTIES  # back-compat name


@dataclass(frozen=True)
class Zone:
    code: int           # WKID passed to ArcGIS services and pyproj
    name: str           # human zone name, e.g. "Washington North"
    label: str          # full CRS label for outputs
    unit: str           # "US survey ft" | "international ft"
    state: str


@lru_cache(maxsize=64)
def make_crs(code: int) -> CRS:
    """EPSG first, then Esri (Esri WKIDs are 5-6 digits like 102696)."""
    try:
        return CRS.from_epsg(code)
    except Exception:  # noqa: BLE001
        return CRS.from_user_input(f"ESRI:{code}")


def ft_per_m(code: int) -> float:
    """Feet (in this CRS's foot) per metre."""
    return 1.0 / make_crs(code).axis_info[0].unit_conversion_factor


def unit_label(code: int) -> str:
    u = make_crs(code).axis_info[0].unit_name.lower()
    if "us survey" in u:
        return "US survey ft"
    if "foot" in u or "feet" in u:
        return "international ft"
    return u


@lru_cache(maxsize=1)
def _zones() -> list[tuple[BaseGeometry, dict]]:
    d = json.loads(ZONES_FILE.read_text())
    return [(shape(f["geometry"]), f["properties"]) for f in d["features"]]


def zone_for_point(lon: float, lat: float, state: str | None = None, county: str | None = None) -> Zone:
    st = (state or "").upper()
    if st == "WA":
        north = (county or "").upper().replace(" COUNTY", "").strip() in WA_NORTH_COUNTIES if county else None
        if north is None:
            p = _match(lon, lat, "WA")
            north = p is not None and p["zone"] == "WA_N"
        code = 2926 if north else 2927
        name = "Washington North" if north else "Washington South"
        return Zone(code, name, f"NAD83(HARN) / {name} (US survey ft)", "US survey ft", "WA")
    p = _match(lon, lat, st or None)
    if p is None:
        raise ValueError(f"No State Plane zone found at {lon:.4f}, {lat:.4f}")
    code = int(p["epsg"])
    unit = unit_label(code)
    return Zone(code, p["name"], f"{_datum(code)} / {p['name']} ({unit})", unit, p["state"])


def _datum(code: int) -> str:
    n = make_crs(code).name
    if " / " in n:
        return n.split(" / ")[0]
    if n.startswith("NAD_1983_2011"):
        return "NAD83(2011)"
    if n.startswith("NAD_1983_HARN"):
        return "NAD83(HARN)"
    return "NAD83"


def _match(lon: float, lat: float, state: str | None) -> dict | None:
    pt = Point(lon, lat)
    hits = [props for geom, props in _zones() if geom.contains(pt)]
    if not hits:  # just outside a simplified coastline: nearest zone within ~1 km
        near = sorted(((geom.distance(pt), props) for geom, props in _zones()), key=lambda t: t[0])
        hits = [p for d, p in near[:3] if d < 0.01]
    if not hits and state:  # offshore island (Sanibel, Maine islands): nearest zone of the same state within ~40 km
        near = sorted(((geom.distance(pt), props) for geom, props in _zones() if props["state"] == state), key=lambda t: t[0])
        hits = [p for d, p in near[:1] if d < 0.4]
    if state:
        same = [h for h in hits if h["state"] == state]
        hits = same or hits
    return hits[0] if hits else None


@lru_cache(maxsize=32)
def transformer(src: int, dst: int) -> Transformer:
    return Transformer.from_crs(make_crs(src), make_crs(dst), always_xy=True)


def reproject(geom: BaseGeometry, src: int, dst: int) -> BaseGeometry:
    if src == dst:
        return geom
    return shp_transform(transformer(src, dst).transform, geom)


def crs_label(code: int) -> str:
    return make_crs(code).name


def wkid_text(code: int) -> str:
    return f"{'EPSG' if code < 100000 else 'ESRI'}:{code}"
