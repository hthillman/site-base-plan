"""Per-dataset fetchers. Each returns a LayerResult and never raises: a failed
fetch becomes status="failed" with the error text, so outputs can show it."""

from __future__ import annotations

import io
import time
import json
import os
from datetime import datetime, timezone

import numpy as np
from shapely import wkt as shp_wkt
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

from ..config import US_FT_PER_M
from ..crs import reproject
from ..http import get_json, plain_session, session
from ..model import Feature, LayerResult, now_iso
from .arcgis import query_features

NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
# Esri Living Atlas copy of the NFHL. Used when FEMA's own server times out or resets connections,
# which it does often under load. It drops minimal-hazard Zone X areas, so "empty" means something different.
NFHL_MIRROR_URL = ("https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
                   "USA_Flood_Hazard_Reduced_Set_gdb/FeatureServer/0")
FEMA_TIMEOUT_S = 12  # one try, then the mirror
NWI_URL = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0"
SDA_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
DEM_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
DEM_INDEX_URL = "https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer"
NAIP_URL = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer"
ESRI_IMAGERY_URL = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer"
# With an ArcGIS Location Platform key, imagery comes from the metered basemap
# tile service (2M tiles/month free) under the key's terms.
# The raster source Esri's own basemap styles service gives for arcgis/imagery
# (metered to the key; it doesn't itself reject unkeyed tile requests).
ESRI_KEYED_TILES = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_IMAGERY_CREDIT = "Imagery: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
NAIP_CREDIT = "Imagery: USDA Farm Production and Conservation Business Center, NAIP"

SFHA_PREFIXES = ("A", "V")  # Zones A, AE, AH, AO, AR, A99, V, VE


def _clip(feats: list[Feature], clip: BaseGeometry) -> list[Feature]:
    out = []
    for f in feats:
        g = f.geom if f.geom.is_valid else make_valid(f.geom)
        g = g.intersection(clip)
        if g.is_empty:
            continue
        if g.geom_type == "GeometryCollection":
            polys = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
            if not polys:
                continue
            from shapely.ops import unary_union

            g = unary_union(polys)
        out.append(Feature(g, f.props))
    return out


def _ms_date(v) -> str:
    """Esri epoch-ms or 'M/D/YYYY h:mm:ss' strings -> YYYY-MM-DD."""
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        return datetime.fromtimestamp(int(v) / 1000, timezone.utc).strftime("%Y-%m-%d")
    s = str(v).split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return str(v)


def _fail(r: LayerResult, e: Exception) -> LayerResult:
    r.status = "failed"
    r.error = f"{type(e).__name__}: {e}"
    r.retrieved_at = now_iso()
    return r


# --------------------------------------------------------------------- flood
def fetch_flood(clip: BaseGeometry, epsg: int) -> LayerResult:
    r = LayerResult(
        key="flood",
        title="FEMA flood hazard zones",
        source="FEMA National Flood Hazard Layer (NFHL), layer 28 Flood Hazard Zones",
        url=f"{NFHL_URL}/28",
        resolution="Mapped at FIRM scale (typically 1:6,000-1:24,000); boundaries are approximate",
        limitations=[
            "Effective FIRM data only; pending or preliminary maps and LOMAs/LOMRs may change zones.",
            "Areas with no digital FIRM return no polygons; that is NOT the same as 'no flood risk'.",
            "Zone boundaries are drawn on older base maps and may not match LiDAR terrain.",
        ],
    )
    fields = "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID"
    try:
        try:
            feats = query_features(f"{NFHL_URL}/28", geometry=clip, in_sr=epsg, out_sr=epsg, out_fields=fields,
                                   max_offset=0.5, timeout=FEMA_TIMEOUT_S, retry=False)
        except Exception as primary:  # noqa: BLE001
            feats = query_features(NFHL_MIRROR_URL, geometry=clip, in_sr=epsg, out_sr=epsg, out_fields=fields, max_offset=0.5)
            return _flood_from_mirror(r, feats, clip, primary)
        r.features = _clip(feats, clip)
        try:
            panels = query_features(f"{NFHL_URL}/3", geometry=clip, in_sr=epsg, out_sr=epsg, out_fields="FIRM_PAN,EFF_DATE,PANEL_TYP")
            effs = sorted({(p.props.get("FIRM_PAN"), _ms_date(p.props.get("EFF_DATE"))) for p in panels})
            if effs:
                r.vintage = "FIRM panel(s) " + ", ".join(f"{p} eff. {d}" for p, d in effs if p)
                r.extra["panels"] = [{"panel": p, "effective": d} for p, d in effs]
            else:
                r.notes.append("No FIRM panel covers this extent (area may be unmapped by FEMA).")
        except Exception as e:  # noqa: BLE001
            r.notes.append(f"Could not read FIRM panel dates: {e}")
        r.status = "ok" if r.features else "empty"
        if not r.features:
            r.notes.append("No NFHL flood zone polygons intersect the extent.")
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


def _flood_from_mirror(r: LayerResult, feats: list, clip: BaseGeometry, primary: Exception) -> LayerResult:
    r.source = "FEMA National Flood Hazard Layer, via Esri Living Atlas copy (USA Flood Hazard Areas, reduced set)"
    r.url = NFHL_MIRROR_URL
    r.extra["fallback"] = True
    try:
        info = get_json(f"{NFHL_MIRROR_URL}", {"f": "json"}, timeout=10)
        ms = (info.get("editingInfo") or {}).get("dataLastEditDate")
        if ms:
            r.vintage = f"Copy of FEMA NFHL as of {_ms_date(ms)}"
    except Exception:  # noqa: BLE001
        pass
    r.notes.append(f"FEMA's own flood service didn't respond ({type(primary).__name__}), so this uses Esri's public copy of the same map.")
    r.notes.append("The copy leaves out minimal-hazard Zone X and has no FIRM panel dates. Check the effective map at msc.fema.gov.")
    r.features = _clip(feats, clip)
    r.status = "ok" if r.features else "empty"
    if not r.features:
        r.notes.append("No 1% or 0.2% annual chance flood zone intersects the extent in the copy.")
    r.retrieved_at = now_iso()
    return r


def is_sfha(props: dict) -> bool:
    z = (props.get("FLD_ZONE") or "").upper()
    return props.get("SFHA_TF") == "T" or (z.startswith(SFHA_PREFIXES) and z != "AREA NOT INCLUDED")


# ------------------------------------------------------------------ wetlands
def fetch_wetlands(clip: BaseGeometry, epsg: int) -> LayerResult:
    r = LayerResult(
        key="wetland",
        title="Wetlands (NWI)",
        source="USFWS National Wetlands Inventory, Wetlands layer",
        url=NWI_URL,
        resolution="Photo-interpreted at ~1:24,000; minimum mapping unit commonly 0.5-5 acres",
        vintage="Varies by project area; most WA mapping derives from 1980s-2010s imagery",
        limitations=[
            "NWI is a screening tool. It misses small, forested, and seasonal wetlands and is not a jurisdictional delineation.",
            "Counties regulate wetlands through their critical-areas ordinances; a qualified wetland biologist must delineate.",
        ],
    )
    try:
        feats = query_features(NWI_URL, geometry=clip, in_sr=epsg, out_sr=epsg, out_fields="ATTRIBUTE,WETLAND_TYPE,ACRES", max_offset=0.5)
        r.features = _clip(feats, clip)
        r.status = "ok" if r.features else "empty"
        if not r.features:
            r.notes.append("No NWI polygons intersect the extent.")
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


# --------------------------------------------------------------------- soils
def fetch_soils(clip: BaseGeometry, epsg: int) -> LayerResult:
    r = LayerResult(
        key="soils",
        title="Soils (SSURGO)",
        source="USDA NRCS Soil Survey Geographic Database (SSURGO) via Soil Data Access",
        url=SDA_URL,
        resolution="Soil survey mapping scale 1:12,000-1:24,000; map units contain inclusions",
        limitations=[
            "Map units are generalized; inclusions of other soils (often 10-25%) are not shown.",
            "Not a substitute for a geotechnical investigation or on-site soil logs (septic, infiltration).",
        ],
    )
    try:
        wkt = reproject(clip, epsg, 4326).wkt
        q = f"""
        SELECT mu.mukey, mu.musym, mu.muname, ma.hydgrpdcd, ma.drclassdcd, ma.hydclprs,
               l.areasymbol, sc.saverest,
               mp.mupolygongeo.STIntersection(geometry::STGeomFromText('{wkt}', 4326)).STAsText() AS geom
        FROM mupolygon mp
        INNER JOIN mapunit mu ON mp.mukey = mu.mukey
        INNER JOIN muaggatt ma ON ma.mukey = mu.mukey
        INNER JOIN legend l ON l.lkey = mu.lkey
        INNER JOIN sacatalog sc ON sc.areasymbol = l.areasymbol
        WHERE mp.mupolygonkey IN (SELECT * FROM SDA_Get_Mupolygonkey_from_intersection_with_WktWgs84('{wkt}'))
        """
        resp = session().post(SDA_URL, json={"format": "JSON+COLUMNNAME", "query": q}, timeout=60)
        resp.raise_for_status()
        rows = resp.json().get("Table", [])
        if not rows:
            r.status = "empty"
            r.notes.append("No SSURGO map units returned for this extent.")
            r.retrieved_at = now_iso()
            return r
        cols, data = rows[0], rows[1:]
        surveys = set()
        for row in data:
            rec = dict(zip(cols, row))
            g = shp_wkt.loads(rec.pop("geom"))
            g = reproject(g, 4326, epsg)
            if g.geom_type == "GeometryCollection":
                from shapely.ops import unary_union

                g = unary_union([p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")])
            if g.is_empty:
                continue
            if not g.is_valid:
                g = make_valid(g)
            surveys.add((rec.get("areasymbol"), _ms_date(rec.get("saverest"))))
            r.features.append(Feature(g, rec))
        r.vintage = "; ".join(f"Survey area {a} version {d}" for a, d in sorted(surveys))
        r.status = "ok" if r.features else "empty"
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


# ----------------------------------------------------------------------- DEM
def _lidar_sources(clip: BaseGeometry, epsg: int) -> list[dict]:
    """Which LiDAR projects built the 3DEP DEM here (layer 11 'DEM - Source')."""
    fields = "project,workunit,collect_start,collect_end,ql,dem_gsd_meters,p_method"
    try:
        feats = query_features(f"{DEM_INDEX_URL}/11", geometry=clip, in_sr=epsg, out_sr=epsg, out_fields=fields, max_offset=10)
        with_geom = True
    except RuntimeError:
        # The index 500s returning very large footprints; attributes still work.
        feats = query_features(f"{DEM_INDEX_URL}/11", geometry=clip, in_sr=epsg, out_sr=epsg, out_fields=fields, return_geometry=False)
        with_geom = False
    seen = {}
    for f in feats:
        p = f.props
        key = p.get("workunit") or p.get("project")
        cover = (f.geom.intersection(clip).area / clip.area if clip.area else 0) if with_geom else None
        if key not in seen or (cover or 0) > (seen[key]["coverage"] or 0):
            seen[key] = {
                "project": p.get("project"), "workunit": p.get("workunit"),
                "collect_start": _ms_date(p.get("collect_start")), "collect_end": _ms_date(p.get("collect_end")),
                "quality_level": p.get("ql"), "dem_gsd_m": p.get("dem_gsd_meters"),
                "method": p.get("p_method"), "coverage": round(cover, 3),
            }
    # Without footprints, assume 3DEP's preference: newest collection wins.
    return sorted(seen.values(), key=lambda s: (-(s["coverage"] or 0), s["collect_end"] or ""), reverse=False) if with_geom else sorted(seen.values(), key=lambda s: s["collect_end"] or "", reverse=True)


USGS_DEM_TIMEOUT_S = 30  # then the backup tiles (USGS can take 40+ s on bad days; 30 s keeps runs under a minute)
TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRAIN_TILES_Z = 15
BACKUP_DEM_RES_M = 10.0  # mostly USGS NED 1/3 arc-second in the US; treated as 10 m for contour limits


def backup_dem(x0: float, y0: float, w: int, h: int, cell_ft: float, epsg: int) -> np.ndarray:
    """Elevation in meters on the same grid as exportImage, from the public AWS Terrain Tiles
    (Mapzen terrarium PNGs, built mostly from USGS NED in the US). Used when 3DEP doesn't answer."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image
    from pyproj import Transformer

    tr = Transformer.from_crs(epsg, 4326, always_xy=True)
    xs = x0 + (np.arange(w) + 0.5) * cell_ft
    ys = y0 + h * cell_ft - (np.arange(h) + 0.5) * cell_ft  # row 0 is the north edge, like exportImage
    X, Y = np.meshgrid(xs, ys)
    lon, lat = tr.transform(X, Y)
    n = 2 ** TERRAIN_TILES_Z
    tx = (lon + 180.0) / 360.0 * n
    lat_r = np.radians(lat)
    ty = (1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / np.pi) / 2.0 * n
    px, py = tx * 256 - 0.5, ty * 256 - 0.5  # pixel space across tiles, pixel centers
    tiles = {(int(a), int(b)) for a in range(int(np.floor(px.min() / 256)), int(np.floor(px.max() / 256)) + 2)
             for b in range(int(np.floor(py.min() / 256)), int(np.floor(py.max() / 256)) + 2)}
    if len(tiles) > 64:
        raise RuntimeError(f"backup elevation would need {len(tiles)} tiles; extent too large")

    def get(t):
        r = session().get(TERRAIN_TILES.format(z=TERRAIN_TILES_Z, x=t[0], y=t[1]), timeout=20)
        r.raise_for_status()
        a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype="float64")
        return t, a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(get, tiles))
    bx0 = min(t[0] for t in got) * 256
    by0 = min(t[1] for t in got) * 256
    W = (max(t[0] for t in got) + 1) * 256 - bx0
    H = (max(t[1] for t in got) + 1) * 256 - by0
    mosaic = np.full((H, W), np.nan)
    for (a, b), arr in got.items():
        mosaic[b * 256 - by0:(b + 1) * 256 - by0, a * 256 - bx0:(a + 1) * 256 - bx0] = arr
    u, v = px - bx0, py - by0
    i0, j0 = np.clip(np.floor(v).astype(int), 0, H - 2), np.clip(np.floor(u).astype(int), 0, W - 2)
    fv, fu = np.clip(v - i0, 0, 1), np.clip(u - j0, 0, 1)
    z = (mosaic[i0, j0] * (1 - fu) * (1 - fv) + mosaic[i0, j0 + 1] * fu * (1 - fv)
         + mosaic[i0 + 1, j0] * (1 - fu) * fv + mosaic[i0 + 1, j0 + 1] * fu * fv)
    z[z < -1000] = np.nan
    return z


def dem_source_resolution(clip: BaseGeometry, epsg: int) -> list[dict]:
    """Finest 3DEP source dataset under the site (centre + corners), from the
    ImageServer's catalog. Returns [centre, corner, corner], each {res_m, title, end_date} or None."""
    from concurrent.futures import ThreadPoolExecutor

    ll = reproject(clip, epsg, 4326)
    x0, y0, x1, y1 = ll.bounds
    pts = [((x0 + x1) / 2, (y0 + y1) / 2), (x0, y0), (x1, y1)]

    def one(pt):
        x, y = pt
        r = session().post(f"{DEM_URL}/identify", data={
            "geometry": json.dumps({"x": x, "y": y, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint", "returnGeometry": "false", "returnCatalogItems": "true", "f": "json"}, timeout=40)
        r.raise_for_status()
        items = [f["attributes"] for f in (r.json().get("catalogItems") or {}).get("features", []) if f["attributes"].get("Category") == 1]
        if not items:
            return None
        top = min(items, key=lambda a: a.get("LowPS") or 99)
        return {"res_m": float(top.get("LowPS") or 99), "title": top.get("title") or top.get("Name"), "end_date": str(top.get("EndDate") or "")}

    with ThreadPoolExecutor(len(pts)) as ex:
        return list(ex.map(one, pts))  # centre first, then corners; None where the catalog has nothing


def fetch_dem(clip: BaseGeometry, epsg: int, cell_ft: float = 3.0, pad_ft: float = 30.0, ft_per_m: float = US_FT_PER_M) -> LayerResult:
    """3DEP best-available DEM, resampled to `cell_ft` on the State Plane grid,
    converted to the CRS's feet (NAVD88)."""
    r = LayerResult(
        key="dem",
        title="Topography (LiDAR DEM)",
        source="USGS 3D Elevation Program (3DEP) best-available DEM, ImageServer exportImage",
        url=DEM_URL,
        limitations=[
            "Bare-earth LiDAR DEM; buildings, walls and recent grading after the flight date are not reflected.",
            "Vertical accuracy depends on LiDAR quality level (QL1 ~10 cm RMSE, QL2 ~10 cm, older data worse); dense vegetation degrades it.",
            "Contours are derived and lightly smoothed for legibility; they are not survey contours.",
        ],
    )
    try:
        x0, y0, x1, y1 = clip.buffer(pad_ft).bounds
        w = int(np.ceil((x1 - x0) / cell_ft))
        h = int(np.ceil((y1 - y0) / cell_ft))
        scale = max(1.0, max(w, h) / 4000)
        if scale > 1:
            cell_ft *= scale
            w = int(np.ceil((x1 - x0) / cell_ft))
            h = int(np.ceil((y1 - y0) / cell_ft))
        x1, y1 = x0 + w * cell_ft, y0 + h * cell_ft
        params = {
            "bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": epsg, "imageSR": epsg, "size": f"{w},{h}",
            "format": "tiff", "pixelType": "F32", "noData": -9999, "noDataInterpretation": "esriNoDataMatchAny",
            "interpolation": "RSP_BilinearInterpolation", "f": "image",
        }
        from concurrent.futures import ThreadPoolExecutor

        side = ThreadPoolExecutor(2)
        fut_res = side.submit(dem_source_resolution, clip, epsg)
        fut_idx = side.submit(_lidar_sources, clip, epsg)
        from PIL import Image

        t_start = time.time()
        try:
            resp = plain_session().get(f"{DEM_URL}/exportImage", params=params, timeout=USGS_DEM_TIMEOUT_S)
            resp.raise_for_status()
            if "image" not in resp.headers.get("Content-Type", ""):
                raise RuntimeError(f"unexpected response: {resp.text[:300]}")
            z = np.asarray(Image.open(io.BytesIO(resp.content)), dtype="float64")  # F32 TIFF -> mode "F"
            if z.shape != (h, w):
                raise RuntimeError(f"DEM came back {z.shape}, expected {(h, w)}")
            z[(z <= -9000) | ~np.isfinite(z)] = np.nan
        except Exception as usgs_err:  # noqa: BLE001 - 3DEP down or slow: use the backup tiles
            z = backup_dem(x0, y0, w, h, cell_ft, epsg)
            side.shutdown(wait=False, cancel_futures=True)
            r.source = "Backup: AWS Terrain Tiles (Mapzen terrarium, built mostly from USGS NED), because USGS 3DEP didn't answer"
            r.url = TERRAIN_TILES
            r.extra["fallback"] = True
            r.extra["source_res_m"] = BACKUP_DEM_RES_M
            r.extra["min_interval_ft"] = 5.0
            r.vintage = "USGS NED-era elevation (mostly 1/3 arc-second, about 10 m), via AWS Terrain Tiles"
            r.resolution = f"About {BACKUP_DEM_RES_M:g} m source; resampled to {cell_ft:.1f} ft grid"
            r.notes.append(f"USGS 3DEP didn't answer within {USGS_DEM_TIMEOUT_S} s ({type(usgs_err).__name__}), so elevation comes from "
                           "the backup source. Run the site again later for LiDAR contours.")
            r.limitations.insert(0, "Elevation is from the coarser backup source (about 10 m), not LiDAR. Contours finer than 5 ft and "
                                    "small slope features are not reliable.")
            if np.isnan(z).all():
                raise RuntimeError("Backup DEM is all no-data for this extent") from usgs_err
            z *= ft_per_m
            r.extra.update(z=z, x0=x0, y0=y0, cell=cell_ft, w=w, h=h, nodata_frac=float(np.isnan(z).mean()))
            r.status = "ok"
            r.retrieved_at = now_iso()
            return r
        if np.isnan(z).all():
            raise RuntimeError("DEM is all no-data for this extent")
        z *= ft_per_m
        r.extra.update(z=z, x0=x0, y0=y0, cell=cell_ft, w=w, h=h, nodata_frac=float(np.isnan(z).mean()))
        r.resolution = f"Resampled to {cell_ft:.1f} ft grid (source GSD below)"
        try:
            srcs = fut_idx.result(timeout=max(1.0, 30 - (time.time() - t_start)))
            r.extra["lidar"] = srcs
            if srcs:
                main = srcs[0]
                gsd = main.get("dem_gsd_m")
                gsd_txt = f"{float(gsd) * ft_per_m:.1f} ft source GSD" if gsd else "source GSD unknown"
                r.vintage = f"{main['project']} (collected {main['collect_start']} to {main['collect_end']}, {main['quality_level']}, {gsd_txt})"
                if len(srcs) > 1:
                    r.notes.append("Additional LiDAR projects overlap: " + "; ".join(f"{s['project']} ({s['collect_end']})" for s in srcs[1:4]))
            else:
                r.vintage = "LiDAR source not reported by 3DEP index (may be 10 m NED in this area)"
        except Exception as e:  # noqa: BLE001
            r.notes.append(f"Could not read 3DEP source index: {e}")
        # Source resolution decides how fine the contours may be.
        try:
            res_by_point = fut_res.result(timeout=max(1.0, 30 - (time.time() - t_start)))
            res = [d for d in res_by_point if d]
        except Exception as e:  # noqa: BLE001
            res, res_by_point = [], []
            r.notes.append(f"Could not read DEM source resolution: {e}")
        if res:
            # Judge by the centre of the site (first point); coarser data at the extent's corners only gets a note.
            centre = res_by_point[0] if res_by_point and res_by_point[0] else res[0]
            worst = round(centre["res_m"], 1)
            edge = max((d["res_m"] for d in res), default=worst)
            if edge > worst + 0.5:
                r.notes.append(f"Part of the extent away from the site is only covered by {edge:g} m elevation data; contours there are less reliable.")
            r.extra["source_res_m"] = worst
            r.extra["min_interval_ft"] = 1.0 if worst <= 2.0 else 2.0 if worst <= 4.0 else 5.0
            d0 = centre
            r.resolution = f"Source {worst:g} m ({d0['title']}); resampled to {cell_ft:.1f} ft grid"
            if not r.vintage or "not reported" in r.vintage:
                r.vintage = f"{d0['title']} (data through {d0['end_date'][:4] or 'n/d'})"
            if worst > 4.0:
                r.notes.append(f"No LiDAR-grade DEM here: 3DEP's finest data under the site is {worst:g} m.")
                r.limitations.insert(0, f"Elevation is from a {worst:g} m DEM (no LiDAR coverage). Contours finer than 5 ft and slope bands are not reliable.")
            elif worst > 2.0:
                r.limitations.insert(0, f"Elevation is from a {worst:g} m LiDAR-derived DEM (older, coarser product). Contours finer than 2 ft are not reliable.")
        if r.extra["nodata_frac"] > 0.01:
            r.notes.append(f"{r.extra['nodata_frac']:.0%} of the DEM grid is no-data (water or coverage gap).")
        r.status = "ok"
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


# ------------------------------------------------------------------- imagery
def fetch_imagery_naip(clip: BaseGeometry, epsg: int, px_ft: float = 1.0) -> LayerResult:
    r = LayerResult(
        key="aerial",
        title="Aerial imagery",
        source="USDA NAIP orthoimagery via USGS The National Map (USGSNAIPImagery ImageServer)",
        url=NAIP_URL,
        limitations=[
            "NAIP is leaf-on agricultural imagery; tree canopy hides ground features and building lean offsets rooftops.",
            "Horizontal accuracy spec is +/- 6 m (~20 ft); do not digitize boundaries from it.",
        ],
    )
    try:
        x0, y0, x1, y1 = clip.bounds
        w = int(np.ceil((x1 - x0) / px_ft))
        h = int(np.ceil((y1 - y0) / px_ft))
        scale = max(1.0, max(w, h) / 4000)
        if scale > 1:
            px_ft *= scale
            w, h = int(np.ceil((x1 - x0) / px_ft)), int(np.ceil((y1 - y0) / px_ft))
        x1, y1 = x0 + w * px_ft, y0 + h * px_ft
        params = {
            "bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": epsg, "imageSR": epsg, "size": f"{w},{h}",
            "format": "jpgpng", "interpolation": "RSP_BilinearInterpolation", "f": "image",
        }
        resp = session().get(f"{NAIP_URL}/exportImage", params=params, timeout=60)
        resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", ""):
            raise RuntimeError(f"unexpected response: {resp.text[:300]}")
        from PIL import Image

        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        arr = np.asarray(img)
        if arr.size == 0 or arr.max() == 0:
            raise RuntimeError("imagery came back empty for this extent")
        r.extra.update(image=img, x0=x0, y0=y0, x1=x1, y1=y1, px=px_ft)
        r.resolution = f"NAIP native 0.6-1 m; exported at {px_ft:.1f} ft/pixel"
        try:
            ll = reproject(box(*clip.bounds), epsg, 4326).bounds
            q = session().get(
                f"{NAIP_URL}/query",
                params={
                    "geometry": json.dumps({"xmin": ll[0], "ymin": ll[1], "xmax": ll[2], "ymax": ll[3]}),
                    "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects", "inSR": 4326,
                    "where": "Category=1", "outFields": "Name,Year,acquisition_date,resolution_value,resolution_units",
                    "returnGeometry": "false", "f": "json",
                },
                timeout=60,
            ).json()
            tiles = [f["attributes"] for f in q.get("features", [])]
            years = sorted({t.get("Year") for t in tiles if t.get("Year")})
            dates = sorted({_ms_date(t.get("acquisition_date")) for t in tiles if t.get("acquisition_date")})
            if dates:
                r.vintage = "Acquired " + ", ".join(dates)
            elif years:
                r.vintage = "NAIP " + ", ".join(map(str, years))
            res = {t.get("resolution_value") for t in tiles if t.get("resolution_value")}
            if res:
                r.resolution = f"NAIP native {', '.join(f'{v:g}' for v in sorted(res))} m; exported at {px_ft:.1f} ft/pixel"
            if years and max(years) < datetime.now().year - 5:
                r.notes.append(f"Imagery is from {max(years)}; site conditions may have changed since.")
        except Exception as e:  # noqa: BLE001
            r.notes.append(f"Could not read imagery acquisition date: {e}")
        r.status = "ok"
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


def _export_size(clip: BaseGeometry, px_ft: float, max_px: int) -> tuple[float, float, float, float, int, int, float]:
    x0, y0, x1, y1 = clip.bounds
    w = int(np.ceil((x1 - x0) / px_ft))
    h = int(np.ceil((y1 - y0) / px_ft))
    if max(w, h) > max_px:
        px_ft *= max(w, h) / max_px
        w, h = int(np.ceil((x1 - x0) / px_ft)), int(np.ceil((y1 - y0) / px_ft))
    return x0, y0, x0 + w * px_ft, y0 + h * px_ft, w, h, px_ft


ESRI_TILE = 1024  # World_Imagery export rejects >1024 px, and anything finer than ~1 ft/px


def _esri_mosaic(x0: float, y1: float, w: int, h: int, px: float, epsg: int):
    """Export the extent in <=1024 px chunks (in parallel) and stitch them."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    def chunk(c0: int, r0: int):
        cw, rh = min(ESRI_TILE, w - c0), min(ESRI_TILE, h - r0)
        bx0, by1 = x0 + c0 * px, y1 - r0 * px
        resp = session().get(
            f"{ESRI_IMAGERY_URL}/export",
            params={"bbox": f"{bx0},{by1 - rh * px},{bx0 + cw * px},{by1}", "bboxSR": epsg, "imageSR": epsg,
                    "size": f"{cw},{rh}", "format": "jpg", "f": "image", "dpi": 96},
            timeout=45,
        )
        resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", ""):
            raise RuntimeError(f"unexpected response: {resp.text[:200]}")
        tile = Image.open(io.BytesIO(resp.content)).convert("RGB")
        if tile.size != (cw, rh):
            tile = tile.resize((cw, rh))
        return c0, r0, tile

    jobs = [(c, r) for r in range(0, h, ESRI_TILE) for c in range(0, w, ESRI_TILE)]
    out = Image.new("RGB", (w, h))
    with ThreadPoolExecutor(max_workers=8) as ex:
        for c0, r0, tile in ex.map(lambda a: chunk(*a), jobs):
            out.paste(tile, (c0, r0))
    return out


def _tile_mosaic(template: str, params: dict, x0: float, y1: float, w: int, h: int, px: float, epsg: int, headers: dict | None = None):
    """Web Mercator XYZ tiles -> State Plane image (bilinear resample)."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    from ..crs import transformer

    # Output pixel centres in State Plane -> Web Mercator metres.
    xs = x0 + (np.arange(w) + 0.5) * px
    ys = y1 - (np.arange(h) + 0.5) * px
    X, Y = np.meshgrid(xs, ys)
    mx, my = transformer(epsg, 3857).transform(X, Y)
    R = 20037508.342789244
    # Zoom whose ground pixel is just finer than the output pixel.
    lat = float(np.degrees(np.arctan(np.sinh(np.pi * float(np.mean(my)) / R))))
    px_m = px * 0.3048006
    z = int(min(19, max(1, np.ceil(np.log2(156543.034 * np.cos(np.radians(lat)) / px_m)))))
    n = 2 ** z
    size = 2 * R / n
    tx0, tx1 = int((mx.min() + R) // size), int((mx.max() + R) // size)
    ty0, ty1 = int((R - my.max()) // size), int((R - my.min()) // size)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 400:
        raise RuntimeError("too many tiles for this extent")

    def get(t):
        tx, ty = t
        resp = session().get(template.format(z=z, x=tx, y=ty), params=params, timeout=30, headers=headers)
        resp.raise_for_status()
        if "image" not in resp.headers.get("Content-Type", ""):
            raise RuntimeError(f"tile service returned {resp.headers.get('Content-Type')}: {resp.text[:120]}")
        return tx, ty, Image.open(io.BytesIO(resp.content)).convert("RGB")

    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tx, ty, im in ex.map(get, [(a, b) for b in range(ty0, ty1 + 1) for a in range(tx0, tx1 + 1)]):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = np.asarray(im.resize((256, 256)))
    # Source pixel coordinates (float) for each output pixel.
    sx = (mx + R) / size * 256 - tx0 * 256 - 0.5
    sy = (R - my) / size * 256 - ty0 * 256 - 0.5
    sx = np.clip(sx, 0, mosaic.shape[1] - 1.001)
    sy = np.clip(sy, 0, mosaic.shape[0] - 1.001)
    ix, iy = sx.astype(int), sy.astype(int)
    fx, fy = (sx - ix)[..., None], (sy - iy)[..., None]
    m = mosaic.astype(np.float32)
    out = (m[iy, ix] * (1 - fx) * (1 - fy) + m[iy, ix + 1] * fx * (1 - fy)
           + m[iy + 1, ix] * (1 - fx) * fy + m[iy + 1, ix + 1] * fx * fy)
    return Image.fromarray(out.astype(np.uint8))


def fetch_imagery_esri(clip: BaseGeometry, epsg: int, px_ft: float = 1.0) -> LayerResult:
    """Esri World Imagery: the current high-res basemap the WA portal maps show.
    Exported straight into State Plane, so no resampling on our side."""
    r = LayerResult(
        key="aerial",
        title="Aerial imagery",
        source="Esri World Imagery (Vantor/Maxar, Earthstar Geographics, local contributors) via ArcGIS Online",
        url=ESRI_IMAGERY_URL,
        limitations=[
            "Satellite/aerial basemap mosaic; capture dates vary across the extent and buildings lean away from nadir.",
            "Stated horizontal accuracy is several metres (see vintage); do not digitize boundaries from it.",
            "Used under Esri's terms for a personal, non-commercial tool. Attribution: Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community.",
        ],
    )
    try:
        x0, y0, x1, y1, w, h, px_ft = _export_size(clip, px_ft, 4096)
        key = os.environ.get("ESRI_API_KEY")
        img = None
        if key:
            try:
                from ..http import esri_headers

                img = _tile_mosaic(ESRI_KEYED_TILES, {"token": key}, x0, y1, w, h, px_ft, epsg, headers=esri_headers())
                r.source += " (basemap tiles, ArcGIS Location Platform key)"
            except Exception as e:  # noqa: BLE001
                r.notes.append(f"Esri API key rejected for imagery ({type(e).__name__}); used the public export instead.")
                print(f"WARN esri key imagery failed: {e}", flush=True)
        if img is None:
            img = _esri_mosaic(x0, y1, w, h, px_ft, epsg)
        r.extra["credit"] = ESRI_IMAGERY_CREDIT
        r.extra.update(image=img, x0=x0, y0=y0, x1=x1, y1=y1, px=px_ft)
        r.resolution = f"Exported at {px_ft:.2f} ft/pixel"
        try:
            ll = reproject(box(*clip.bounds), epsg, 4326).bounds
            q = session().post(
                f"{ESRI_IMAGERY_URL}/0/query",
                data={"geometry": json.dumps({"xmin": ll[0], "ymin": ll[1], "xmax": ll[2], "ymax": ll[3]}),
                      "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                      "where": "MinMapLevel >= 12", "outFields": "SRC_DATE2,SRC_RES,SRC_ACC,SRC_DESC,NICE_NAME,NICE_DESC,DrawOrder",
                      "returnGeometry": "false", "f": "json"},
                timeout=60,
            ).json()
            tiles = sorted((f["attributes"] for f in q.get("features", [])), key=lambda a: -(a.get("DrawOrder") or 0))
            if tiles:
                top = tiles[0]
                r.vintage = (f"Captured {_ms_date(top.get('SRC_DATE2'))}, {top.get('NICE_DESC')} {top.get('NICE_NAME')} ({top.get('SRC_DESC')}), "
                             f"{top.get('SRC_RES')} m, stated accuracy {top.get('SRC_ACC')} m")
                r.resolution = f"Source {top.get('SRC_RES')} m; exported at {px_ft:.2f} ft/pixel"
                r.extra["sources"] = tiles
                others = sorted({_ms_date(t.get("SRC_DATE2")) for t in tiles[1:] if t.get("SRC_DATE2")})
                if others:
                    r.notes.append("Other capture dates in the extent: " + ", ".join(others))
                yr = int(_ms_date(top.get("SRC_DATE2"))[:4] or 0)
                if yr and yr < datetime.now().year - 5:
                    r.notes.append(f"Imagery is from {yr}; site conditions may have changed since.")
        except Exception as e:  # noqa: BLE001
            r.notes.append(f"Could not read imagery capture date: {e}")
        r.status = "ok"
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


def fetch_imagery(clip: BaseGeometry, epsg: int) -> LayerResult:
    """Newest imagery first (Esri World Imagery); public-domain NAIP if it fails."""
    r = fetch_imagery_esri(clip, epsg)
    if r.ok():
        return r
    fallback = fetch_imagery_naip(clip, epsg)
    fallback.extra["credit"] = NAIP_CREDIT
    fallback.notes.insert(0, f"Esri World Imagery failed ({r.error}); fell back to NAIP.")
    return fallback


# ------------------------------------------------------------------- roads
TIGER_ROADS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer"
ROAD_LAYERS = {2: "primary", 6: "secondary", 8: "local"}


def fetch_roads(clip: BaseGeometry, epsg: int) -> LayerResult:
    r = LayerResult(
        key="roads", title="Road centerlines", source="U.S. Census Bureau TIGER/Line roads via TIGERweb",
        url=TIGER_ROADS,
        resolution="TIGER centerlines; positional accuracy typically 5-40 ft (better in cities)",
        vintage="Current TIGERweb release",
        limitations=["Centerlines are approximate and don't show pavement edges, curbs or right-of-way width.",
                     "Private drives and some new streets may be missing; names follow Census conventions."],
    )
    try:
        seen = set()
        for layer, cls in ROAD_LAYERS.items():
            for f in query_features(f"{TIGER_ROADS}/{layer}", geometry=clip.buffer(50), in_sr=epsg, out_sr=epsg, out_fields="NAME,MTFCC,RTTYP"):
                g = f.geom.intersection(clip)
                if g.is_empty:
                    continue
                key = (round(g.centroid.x), round(g.centroid.y), round(g.length))
                if key in seen:
                    continue
                seen.add(key)
                r.features.append(Feature(g, {"name": (f.props.get("NAME") or "").strip(), "class": cls, "mtfcc": f.props.get("MTFCC")}))
        r.status = "ok" if r.features else "empty"
        if not r.features:
            r.notes.append("No mapped roads in the extent.")
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


# ---------------------------------------------------------------- buildings
STRUCTURES_URL = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/USA_Structures_View/FeatureServer/0"
ASSUMED_HEIGHT_M = 4.5  # one story, when a structure has no height


def _usa_structures(clip: BaseGeometry, epsg: int) -> list[Feature]:
    feats = query_features(STRUCTURES_URL, geometry=clip, in_sr=epsg, out_sr=epsg,
                           out_fields="HEIGHT,OCC_CLS,PRIM_OCC,IMAGE_DATE,SOURCE,VAL_METHOD,OUTBLDG")
    out = []
    for f in feats:
        g = f.geom if f.geom.is_valid else make_valid(f.geom)
        if not g.is_empty:
            out.append(Feature(g, f.props))
    return out


def _usa_height_m(props: dict) -> float | None:
    h = props.get("HEIGHT")
    return float(h) if isinstance(h, (int, float)) and 2 <= h <= 400 else None


MS_FOOTPRINTS_URL = "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/MSBFP2/FeatureServer/0"


def _microsoft_source():
    from ..footprints import BuildingSource

    return BuildingSource(state="", name="Microsoft US Building Footprints", publisher="Microsoft, hosted by Esri Living Atlas",
                          url=MS_FOOTPRINTS_URL, method="machine-traced from imagery", vintage="Microsoft footprints (imagery about 2014 to 2022)",
                          terms="ODbL 1.0; contains Microsoft US Building Footprints data", max_record_count=2000)


def fetch_buildings(clip: BaseGeometry, epsg: int, ft_per_m: float, state: str | None = None, county: str | None = None) -> LayerResult:
    """Existing building footprints with heights, for plan outlines and 3D massing. In order: a county/city/state planimetric
    layer from the footprint registry; Microsoft's nationwide footprints (machine-traced but much closer to roofs than USA
    Structures in our comparisons), with heights matched from USA Structures; USA Structures alone as the last resort."""
    from ..footprints import sources_for

    srcs = sources_for(state, county)
    src = srcs[0] if srcs else None
    notes = []
    try:
        for cand in srcs:
            try:
                r = _buildings_from_registry(cand, clip, epsg, ft_per_m)
                if r.status == "ok":
                    r.notes[:0] = notes
                    return r
                notes.append(f"{cand.label} has no outlines here.")
            except Exception as e:  # noqa: BLE001 - quota, outage, moved service: fall back, never fail the layer
                notes.append(f"{cand.label} didn't answer ({type(e).__name__}).")
        try:
            r = _buildings_from_registry(_microsoft_source(), clip, epsg, ft_per_m)
        except Exception as e:  # noqa: BLE001 - fall through to USA Structures
            r = None
            notes.append(f"Microsoft footprints didn't load ({type(e).__name__}).")
        if r is not None and r.status == "ok":
            r.extra["planimetric"] = False
            r.extra["machine"] = "microsoft"
            r.extra["quality"] = "microsoft"
            r.resolution = "Machine-traced from aerial imagery by Microsoft; heights matched from FEMA USA Structures where they overlap"
            r.limitations = ["Outlines are machine-traced from aerial imagery (Microsoft), not surveyed: usually close to the roof but "
                             "simplified, sometimes a few feet off, and they can miss buildings or mark tree canopy as a building.",
                             "Heights come from FEMA USA Structures where a footprint overlaps one; others are drawn one story.",
                             "Massing is a simple flat-roofed block at each building's height."]
            r.notes[:0] = notes
            return r
        r = _buildings_from_usa_structures(clip, epsg, ft_per_m)
        r.notes[:0] = notes
        return r
    except Exception as e:  # noqa: BLE001
        r = LayerResult(key="buildings", title="Existing buildings", source=src.label if src else "FEMA / ORNL USA Structures",
                        url=src.url if src else STRUCTURES_URL)
        return _fail(r, e)


def _buildings_from_registry(src, clip: BaseGeometry, epsg: int, ft_per_m: float) -> LayerResult:
    r = LayerResult(
        key="buildings", title="Existing buildings", source=src.label, url=src.url,
        resolution=f"{(src.method or 'Published').capitalize()} building outlines from {src.publisher or src.name}",
        vintage=src.vintage,
        limitations=["Outlines as published by the local government; check the date against recent construction.",
                     "Massing is a simple flat-roofed block at each building's height."],
    )
    where = src.filter or "1=1"
    feats = query_features(src.url, geometry=clip, in_sr=epsg, out_sr=epsg, where=where, out_fields=src.out_fields())
    feats = [Feature(f.geom if f.geom.is_valid else make_valid(f.geom), f.props) for f in feats]
    feats = [f for f in feats if not f.geom.is_empty and f.geom.area >= 50 and f.geom.intersects(clip)]  # keep buildings straddling the edge
    if not feats:
        r.status = "empty"
        r.retrieved_at = now_iso()
        return r
    usa = None
    from_layer = matched = assumed = 0
    for f in feats:
        h = src.height_ft(f.props, ft_per_m)
        how = "layer"
        if h is None:
            if usa is None:
                try:
                    usa = _usa_structures(clip, epsg)
                except Exception:  # noqa: BLE001 - heights are a nice-to-have
                    usa = []
            best, best_a = None, 0.0
            for u in usa:
                a = u.geom.intersection(f.geom).area if u.geom.intersects(f.geom) else 0.0
                if a > best_a:
                    best, best_a = u, a
            hm = _usa_height_m(best.props) if best is not None and best_a > 0.3 * min(best.geom.area, f.geom.area) else None
            if hm is not None:
                h, how = hm * ft_per_m, "usa"
            else:
                h, how = ASSUMED_HEIGHT_M * ft_per_m, "assumed"
        from_layer += how == "layer"
        matched += how == "usa"
        assumed += how == "assumed"
        r.features.append(Feature(f.geom, {"height_ft": round(h, 1), "height_assumed": how == "assumed", "height_source": how,
                                           "use": "", "type": "", "image_date": "", "verified": src.method or ""}))
    parts = []
    if from_layer:
        parts.append(f"{from_layer} from the layer")
    if matched:
        parts.append(f"{matched} matched from FEMA USA Structures")
    if assumed:
        parts.append(f"{assumed} assumed one story ({ASSUMED_HEIGHT_M * ft_per_m:.0f} ft)")
    r.notes.append("Building heights: " + "; ".join(parts) + ".")
    r.extra["planimetric"] = True
    r.extra["quality"] = "local"
    r.extra["method"] = src.method
    r.status = "ok"
    r.retrieved_at = now_iso()
    return r


def _buildings_from_usa_structures(clip: BaseGeometry, epsg: int, ft_per_m: float) -> LayerResult:
    r = LayerResult(
        key="buildings", title="Existing buildings", source="FEMA / Oak Ridge National Laboratory USA Structures (via Esri)",
        url=STRUCTURES_URL,
        resolution="Footprints traced from imagery; heights estimated from LiDAR or imagery. Structures under 450 sq ft are not included.",
        limitations=["Footprints are machine-learning traces of aerial imagery (FEMA/ORNL), not surveyed or planimetric outlines: "
                     "commonly a few feet off, simplified, and missing small or tree-covered buildings. Heights are estimates.",
                     "Buildings built or removed since the source imagery date won't match.",
                     "Massing is a simple flat-roofed block at each building's estimated height."],
    )
    dates, assumed = set(), 0
    for f in _usa_structures(clip, epsg):
        if not f.geom.intersects(clip):
            continue
        hm = _usa_height_m(f.props)
        if hm is None:
            assumed += 1
        d = _ms_date(f.props.get("IMAGE_DATE"))
        if d:
            dates.add(d[:4])
        r.features.append(Feature(f.geom, {"height_ft": round((hm or ASSUMED_HEIGHT_M) * ft_per_m, 1), "height_assumed": hm is None,
                                           "height_source": "usa" if hm else "assumed",
                                           "use": f.props.get("OCC_CLS") or "", "type": f.props.get("PRIM_OCC") or "",
                                           "image_date": d or "", "verified": f.props.get("VAL_METHOD") or ""}))
    if dates:
        r.vintage = "Source imagery " + (min(dates) if min(dates) == max(dates) else f"{min(dates)} to {max(dates)}")
    if assumed:
        r.notes.append(f"{assumed} building(s) had no height in the source and are drawn one story ({ASSUMED_HEIGHT_M * ft_per_m:.0f} ft) tall.")
    r.extra["quality"] = "fema"
    r.status = "ok" if r.features else "empty"
    if not r.features:
        r.notes.append("No structures over 450 sq ft mapped in the extent.")
    r.retrieved_at = now_iso()
    return r


# --------------------------------------------------------- adjacent parcels
def fetch_adjacent(clip: BaseGeometry, epsg: int, src, subject_geom: BaseGeometry | None) -> LayerResult:
    """Every tax parcel in the extent other than the subject, normalised
    (_APN, _OWNER, _DEED, _PLAT ...) for labels."""
    from ..parcel import _normalise

    r = LayerResult(
        key="adjacent", title="Adjacent parcels", source=src.label if src else "no parcel source",
        url=src.url if src else "",
        resolution="Assessor tax-lot mapping; typical positional error 5-50 ft",
        vintage=src.vintage if src else "",
        limitations=["Tax parcels, not legal boundaries.",
                     "Owner, deed and plat fields appear only where the publisher includes them."
                     + (f" This source has: {', '.join(n for n, f in (('owner', src.owner_field), ('deed', src.deed_book_field or src.deed_ref_field), ('plat', src.plat_book_field or src.plat_ref_field), ('legal', src.legal_field)) if f) or 'parcel IDs only'}." if src else "")],
    )
    if src is None:
        r.status = "skipped"
        r.error = "No parcel layer for this location."
        r.retrieved_at = now_iso()
        return r
    try:
        feats = [_normalise(f, src) for f in query_features(src.url, geometry=clip, in_sr=epsg, out_sr=epsg)]
        for f in feats:
            if subject_geom is not None and f.geom.intersection(subject_geom).area > 0.5 * min(f.geom.area, subject_geom.area):
                continue  # the subject parcel itself (or a stacked duplicate)
            g = f.geom if f.geom.is_valid else make_valid(f.geom)
            g = g.intersection(clip)
            if g.is_empty or g.area < 20:
                continue
            r.features.append(Feature(g, {**f.props, "_FULL_AREA": f.geom.area}))
        r.extra["all_parcels"] = [f.geom for f in feats]
        r.status = "ok" if r.features else "empty"
    except Exception as e:  # noqa: BLE001
        return _fail(r, e)
    r.retrieved_at = now_iso()
    return r


def derive_row(clip: BaseGeometry, parcels: list[BaseGeometry], roads: list[BaseGeometry], min_area: float = 300.0) -> list[Feature]:
    """Area inside the extent that isn't in any tax parcel. Where parcel
    coverage is complete that's almost always road right-of-way (sometimes
    water or rail). Only pieces a road centerline runs through are kept, so
    unmapped gaps aren't mislabelled."""
    from shapely.ops import unary_union

    if not parcels:
        return []
    covered = unary_union([p.buffer(0.5) for p in parcels])
    gap = clip.difference(covered)
    parts = list(getattr(gap, "geoms", [gap]))
    road_u = unary_union(roads) if roads else None
    out = []
    for g in parts:
        if g.is_empty or g.area < min_area or g.geom_type != "Polygon":
            continue
        # Thin it of slivers between adjacent parcels.
        g2 = g.buffer(-1.5).buffer(1.5)
        if g2.is_empty or g2.area < min_area:
            continue
        if road_u is not None and not g2.intersects(road_u):
            continue
        out.append(Feature(g2, {"label": "Approximate right-of-way (area between tax parcels)"}))
    return out
