"""Minimal ArcGIS REST helpers: paged feature queries, Esri JSON -> shapely."""

from __future__ import annotations

import json
from typing import Any

from shapely.geometry import LinearRing, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

from ..http import get_json, session
from ..model import Feature


def esri_polygon(rings: list[list[list[float]]]) -> BaseGeometry | None:
    """Esri rings: clockwise = exterior, counter-clockwise = hole."""
    shells: list[Polygon] = []
    holes: list[list] = []
    for r in rings:
        if len(r) < 4:
            continue
        ring = LinearRing([p[:2] for p in r])
        (holes if ring.is_ccw else shells).append(ring)
    if not shells and holes:  # some services ignore the convention
        shells, holes = holes, []
    polys = []
    for s in shells:
        sp = Polygon(s)
        mine = [h for h in holes if sp.contains(Polygon(h).representative_point())]
        polys.append(Polygon(s, mine))
    if not polys:
        return None
    g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return g if g.is_valid else make_valid(g)


def esri_geometry(g: dict) -> BaseGeometry | None:
    if not g:
        return None
    if "rings" in g:
        return esri_polygon(g["rings"])
    if "paths" in g:
        from shapely.geometry import LineString, MultiLineString

        lines = [LineString([p[:2] for p in path]) for path in g["paths"] if len(path) > 1]
        return lines[0] if len(lines) == 1 else MultiLineString(lines)
    if "x" in g:
        from shapely.geometry import Point

        return Point(g["x"], g["y"])
    return None


def query_features(
    layer_url: str,
    *,
    geometry: BaseGeometry | None = None,
    in_sr: int | None = None,
    out_sr: int,
    where: str = "1=1",
    out_fields: str = "*",
    max_offset: float | None = None,
    page_size: int | None = None,
    return_geometry: bool = True,
    timeout: float = 45,
) -> list[Feature]:
    params: dict[str, Any] = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true" if return_geometry else "false",
        "outSR": out_sr,
        "f": "json",
    }
    if geometry is not None:
        if geometry.geom_type == "Polygon" and geometry.equals(geometry.envelope):
            x0, y0, x1, y1 = geometry.bounds
            params["geometry"] = json.dumps({"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1})
            params["geometryType"] = "esriGeometryEnvelope"
        elif geometry.geom_type == "Point":
            params["geometry"] = f"{geometry.x},{geometry.y}"
            params["geometryType"] = "esriGeometryPoint"
        else:
            poly = geometry if geometry.geom_type == "Polygon" else geometry.convex_hull
            params["geometry"] = json.dumps({"rings": [list(map(list, poly.exterior.coords))]})
            params["geometryType"] = "esriGeometryPolygon"
        params["spatialRel"] = "esriSpatialRelIntersects"
        params["inSR"] = in_sr or out_sr
    if max_offset:
        params["maxAllowableOffset"] = max_offset
    out: list[Feature] = []
    offset = 0
    for _ in range(50):
        p = dict(params)
        if offset or page_size:
            p["resultOffset"] = offset
            if page_size:
                p["resultRecordCount"] = page_size
        # Long polygon geometries blow past URL limits; POST is always safe.
        r = session().post(f"{layer_url}/query", data=p, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            e = data["error"]
            raise RuntimeError(f"{layer_url}: {e.get('code')} {e.get('message')} {e.get('details') or ''}")
        feats = data.get("features", [])
        for f in feats:
            if not return_geometry:
                from shapely.geometry import GeometryCollection

                out.append(Feature(GeometryCollection(), f.get("attributes", {})))
                continue
            g = esri_geometry(f.get("geometry"))
            if g is not None and not g.is_empty:
                out.append(Feature(g, f.get("attributes", {})))
        if not data.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return out


def layer_info(layer_url: str) -> dict:
    return get_json(layer_url, {"f": "json"})


def geojson_geometry(g: dict) -> BaseGeometry:
    return shape(g)
