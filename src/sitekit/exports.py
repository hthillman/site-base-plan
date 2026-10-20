"""Extra export formats beyond DXF/DWG/PDF:

- terrain.dae / terrain.obj: textured terrain mesh (aerial draped) plus the
  parcel line draped on it, in the same 0,0-based coordinates as
  site-local.dxf. COLLADA imports into every SketchUp edition (incl. Free/Go);
  OBJ for Rhino, Blender, 3ds Max.
- surface.xml: LandXML 1.2 TIN surface in true State Plane, for Civil 3D.
- gis/*.geojson: every vector layer in WGS84 (RFC 7946) for QGIS/ArcGIS.
- site.kml: parcel, flood, wetland and major contours for Google Earth.
- dem.tif gets GeoTIFF tags (EPSG codes) on top of its .tfw/.prj sidecars.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry

from .crs import reproject
from .export_dxf import base_point

MAX_MESH_VERTS = 60_000


# ------------------------------------------------------------------ mesh
def _mesh(grid, clip, max_verts: int = MAX_MESH_VERTS):
    """Decimated regular-grid TIN over the clip box. Returns xs, ys (1-D, true
    coordinates), Z (2-D, NaN = hole), and triangle index list."""
    h, w = grid.z.shape
    xs_all, ys_all = grid.centers()
    x0, y0, x1, y1 = clip.bounds
    ci = np.where((xs_all >= x0) & (xs_all <= x1))[0]
    ri = np.where((ys_all >= y0) & (ys_all <= y1))[0]
    step = max(1, math.ceil(math.sqrt(len(ci) * len(ri) / max_verts)))
    ci, ri = ci[::step], ri[::step]
    Z = grid.z[np.ix_(ri, ci)]
    xs, ys = xs_all[ci], ys_all[ri]
    nr, nc = Z.shape
    idx = np.arange(nr * nc).reshape(nr, nc)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    ok = np.isfinite(Z).ravel()
    t1 = np.stack([a, c, b], 1)  # rows run north->south, so (a,c,b) is CCW seen from above
    t2 = np.stack([b, c, d], 1)
    tris = np.concatenate([t1, t2])
    tris = tris[ok[tris].all(axis=1)]
    return xs, ys, Z, tris, step * grid.cell


def _drape(line: LineString, grid, spacing: float) -> list[tuple[float, float, float]]:
    xs, ys = grid.centers()
    pts = []
    n = max(2, int(line.length / spacing) + 1)
    for i in range(n):
        p = line.interpolate(i / (n - 1), normalized=True)
        cx = int(np.clip(round((p.x - xs[0]) / grid.cell), 0, len(xs) - 1))
        cy = int(np.clip(round((ys[0] - p.y) / grid.cell), 0, len(ys) - 1))
        z = grid.z[cy, cx]
        if np.isfinite(z):
            pts.append((p.x, p.y, float(z) + 0.5))  # lift slightly so it draws over the surface
    return pts


def _rings(g: BaseGeometry) -> list[LineString]:
    polys = [g] if isinstance(g, Polygon) else list(g.geoms) if isinstance(g, MultiPolygon) else []
    return [LineString(r.coords) for p in polys for r in [p.exterior, *p.interiors]]


def write_terrain(res, grid, out: Path) -> dict[str, str]:
    site = res.site
    xs, ys, Z, tris, spacing = _mesh(grid, site.clip)
    bx, by = base_point(site.clip)
    X, Y = np.meshgrid(xs, ys)
    V = np.stack([X.ravel() - bx, Y.ravel() - by, np.nan_to_num(Z.ravel(), nan=0.0)], 1)
    ae = res.layers.get("aerial")
    tex = None
    if ae is not None and ae.ok():
        tex = "terrain_texture.jpg"
        ae.extra["image"].save(out / tex, quality=88)
        U = (X.ravel() - ae.extra["x0"]) / (ae.extra["x1"] - ae.extra["x0"])
        Vt = (Y.ravel() - ae.extra["y0"]) / (ae.extra["y1"] - ae.extra["y0"])
        UV = np.stack([U, Vt], 1)
    lines = []
    if site.parcel is not None:
        for ring in _rings(site.parcel.geom):
            pts = _drape(ring, grid, 5.0)
            if len(pts) > 1:
                lines.append([(x - bx, y - by, z) for x, y, z in pts])

    from .massing import blocks, mesh

    groups: dict[str, tuple[list, list]] = {}
    for blk in blocks(res, grid):
        vs, ts = mesh(blk, bx, by)
        gv, gt = groups.setdefault(blk.kind, ([], []))
        off = len(gv)
        gv += vs
        gt += [(a + off, b + off, c + off) for a, b, c in ts]
    mats = {"existing": ("buildings", "Existing buildings (massing)", "0.86 0.85 0.81", 1.0),
            "envelope": ("envelope", "Zoning envelope (massing)", "0.30 0.56 0.88", 0.35)}

    files = {}
    # ---- OBJ
    with open(out / "terrain.obj", "w") as f:
        f.write(f"# Terrain mesh, {site.units}, origin at base point E {bx:.0f} N {by:.0f} ({site.crs_label}); Z = elevation NAVD88\n")
        f.write("# Planning-level data only; not a survey.\n")
        if tex or groups:
            f.write("mtllib terrain.mtl\n")
        f.writelines(f"v {x:.2f} {y:.2f} {z:.2f}\n" for x, y, z in V)
        if tex:
            f.writelines(f"vt {u:.5f} {v:.5f}\n" for u, v in UV)
            f.write("usemtl aerial\n")
            f.writelines(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n" for a, b, c in tris)
        else:
            f.writelines(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in tris)
        base = len(V)
        for ln in lines:
            f.writelines(f"v {x:.2f} {y:.2f} {z:.2f}\n" for x, y, z in ln)
            f.write("l " + " ".join(str(base + i + 1) for i in range(len(ln))) + "\n")
            base += len(ln)
        for kind, (gv, gt) in groups.items():
            mid, label, _, _ = mats[kind]
            f.write(f"o {label.replace(' ', '_')}\nusemtl {mid}\n")
            f.writelines(f"v {x:.2f} {y:.2f} {z:.2f}\n" for x, y, z in gv)
            f.writelines(f"f {base + a + 1} {base + b + 1} {base + c + 1}\n" for a, b, c in gt)
            base += len(gv)
    if tex or groups:
        mtl = f"newmtl aerial\nKa 1 1 1\nKd 1 1 1\nmap_Kd {tex}\n" if tex else ""
        mtl += "".join(f"newmtl {mid}\nKd {rgb}\nd {alpha}\n" for mid, _, rgb, alpha in mats.values())
        (out / "terrain.mtl").write_text(mtl)
    files["terrain_obj"] = str(out / "terrain.obj")

    # ---- COLLADA 1.4.1
    def floats(a):
        return " ".join(f"{v:.2f}" for v in np.asarray(a).ravel())

    tri_p = " ".join(f"{i}" for t in tris for i in t) if not tex else " ".join(f"{i} {i}" for t in tris for i in t)
    line_geoms = ""
    line_nodes = ""
    for k, ln in enumerate(lines):
        pos = floats(ln)
        line_geoms += f"""
    <geometry id="parcel{k}" name="parcel line {k}"><mesh>
      <source id="parcel{k}-pos"><float_array id="parcel{k}-pos-a" count="{len(ln) * 3}">{pos}</float_array>
        <technique_common><accessor source="#parcel{k}-pos-a" count="{len(ln)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
      <vertices id="parcel{k}-v"><input semantic="POSITION" source="#parcel{k}-pos"/></vertices>
      <lines count="{len(ln) - 1}" material="red"><input semantic="VERTEX" source="#parcel{k}-v" offset="0"/><p>{" ".join(f"{i} {i + 1}" for i in range(len(ln) - 1))}</p></lines>
    </mesh></geometry>"""
        line_nodes += f'<node id="parcel-node{k}" name="Parcel line"><instance_geometry url="#parcel{k}"><bind_material><technique_common><instance_material symbol="red" target="#red-mat"/></technique_common></bind_material></instance_geometry></node>'
    mass_geoms = ""
    mass_nodes = ""
    mass_fx = ""
    mass_mats = ""
    for kind, (gv, gt) in groups.items():
        mid, label, rgb, alpha = mats[kind]
        mass_geoms += f"""
    <geometry id="{mid}" name="{label}"><mesh>
      <source id="{mid}-pos"><float_array id="{mid}-pos-a" count="{len(gv) * 3}">{floats(gv)}</float_array>
        <technique_common><accessor source="#{mid}-pos-a" count="{len(gv)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
      <vertices id="{mid}-v"><input semantic="POSITION" source="#{mid}-pos"/></vertices>
      <triangles count="{len(gt)}" material="{mid}"><input semantic="VERTEX" source="#{mid}-v" offset="0"/><p>{" ".join(str(i) for t in gt for i in t)}</p></triangles>
    </mesh></geometry>"""
        mass_nodes += f'<node id="{mid}-node" name="{label}"><instance_geometry url="#{mid}"><bind_material><technique_common><instance_material symbol="{mid}" target="#{mid}-mat"/></technique_common></bind_material></instance_geometry></node>'
        mass_fx += (f'<effect id="{mid}-fx"><profile_COMMON><technique sid="t"><lambert><diffuse><color>{rgb} 1</color></diffuse>'
                    + (f'<transparent opaque="A_ONE"><color>{rgb} {alpha}</color></transparent><transparency><float>1</float></transparency>' if alpha < 1 else "")
                    + "</lambert></technique></profile_COMMON></effect>")
        mass_mats += f'<material id="{mid}-mat" name="{label}"><instance_effect url="#{mid}-fx"/></material>'
    uv_src = ""
    uv_in = ""
    if tex:
        uv_src = f"""<source id="terrain-uv"><float_array id="terrain-uv-a" count="{len(UV) * 2}">{" ".join(f"{v:.5f}" for v in UV.ravel())}</float_array>
        <technique_common><accessor source="#terrain-uv-a" count="{len(UV)}" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>"""
        uv_in = '<input semantic="TEXCOORD" source="#terrain-uv" offset="1" set="0"/>'
    effect = (f"""<effect id="aerial-fx"><profile_COMMON>
      <newparam sid="surf"><surface type="2D"><init_from>tex-img</init_from></surface></newparam>
      <newparam sid="samp"><sampler2D><source>surf</source></sampler2D></newparam>
      <technique sid="t"><lambert><diffuse><texture texture="samp" texcoord="UV"/></diffuse></lambert></technique></profile_COMMON></effect>"""
              if tex else '<effect id="aerial-fx"><profile_COMMON><technique sid="t"><lambert><diffuse><color>0.6 0.55 0.45 1</color></diffuse></lambert></technique></profile_COMMON></effect>')
    dae = f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><contributor><authoring_tool>Basesheet (basesheet.site)</authoring_tool><comments>{escape(f"Terrain, origin at base point E {bx:.0f} N {by:.0f}, {site.crs_label}. Elevations NAVD88 {site.units}. Planning-level data only; not a survey.")}</comments></contributor>
    <unit name="foot" meter="0.3048"/><up_axis>Z_UP</up_axis></asset>
  {'<library_images><image id="tex-img"><init_from>' + tex + '</init_from></image></library_images>' if tex else ''}
  <library_effects>{effect}
    <effect id="red-fx"><profile_COMMON><technique sid="t"><constant><emission><color>0.84 0.15 0.16 1</color></emission></constant></technique></profile_COMMON></effect>{mass_fx}</library_effects>
  <library_materials><material id="aerial-mat"><instance_effect url="#aerial-fx"/></material><material id="red-mat"><instance_effect url="#red-fx"/></material>{mass_mats}</library_materials>
  <library_geometries>
    <geometry id="terrain" name="terrain"><mesh>
      <source id="terrain-pos"><float_array id="terrain-pos-a" count="{len(V) * 3}">{floats(V)}</float_array>
        <technique_common><accessor source="#terrain-pos-a" count="{len(V)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
      {uv_src}
      <vertices id="terrain-v"><input semantic="POSITION" source="#terrain-pos"/></vertices>
      <triangles count="{len(tris)}" material="aerial"><input semantic="VERTEX" source="#terrain-v" offset="0"/>{uv_in}<p>{tri_p}</p></triangles>
    </mesh></geometry>{line_geoms}{mass_geoms}
  </library_geometries>
  <library_visual_scenes><visual_scene id="scene"><node id="terrain-node" name="Terrain"><instance_geometry url="#terrain"><bind_material><technique_common><instance_material symbol="aerial" target="#aerial-mat">{'<bind_vertex_input semantic="UV" input_semantic="TEXCOORD" input_set="0"/>' if tex else ''}</instance_material></technique_common></bind_material></instance_geometry></node>{line_nodes}{mass_nodes}</visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#scene"/></scene>
</COLLADA>
"""
    (out / "terrain.dae").write_text(dae)
    files["terrain_dae"] = str(out / "terrain.dae")
    res.layers["dem"].notes.append(f"Terrain mesh: {len(tris):,} triangles at {spacing:.1f} ft spacing.")
    if groups:
        n_b = sum(1 for b in blocks(res, grid) if b.kind == "existing")
        res.layers["dem"].notes.append(f"3D massing in terrain.dae / terrain.obj: {n_b} existing building block(s)"
                                       + (" plus the zoning envelope" if "envelope" in groups else "") + ".")
    return files


# --------------------------------------------------------------- LandXML
def write_landxml(res, grid, out: Path) -> str:
    site = res.site
    xs, ys, Z, tris, spacing = _mesh(grid, site.clip, max_verts=250_000)
    X, Y = np.meshgrid(xs, ys)
    Xr, Yr, Zr = X.ravel(), Y.ravel(), Z.ravel()
    used = np.unique(tris)
    newid = {int(o): i + 1 for i, o in enumerate(used)}
    unit = "USSurveyFoot" if "US survey" in site.units else "foot"
    pts = "\n".join(f'<P id="{newid[int(i)]}">{Yr[i]:.3f} {Xr[i]:.3f} {Zr[i]:.3f}</P>' for i in used)  # LandXML order: N E Z
    faces = "\n".join(f"<F>{newid[int(a)]} {newid[int(c)]} {newid[int(b)]}</F>" for a, b, c in tris)  # clockwise from above
    zs = Zr[used]
    from .crs import wkid_text

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" date="{__import__('datetime').date.today().isoformat()}" time="00:00:00">
  <Units><Imperial areaUnit="squareFoot" linearUnit="{unit}" volumeUnit="cubicFeet" temperatureUnit="fahrenheit" pressureUnit="inHG" angularUnit="decimal degrees" directionUnit="decimal degrees"/></Units>
  <CoordinateSystem name="{escape(site.crs_label)}" desc="{wkid_text(site.epsg)}; vertical NAVD88"/>
  <Application name="Basesheet" desc="Planning-level data only; not a survey"/>
  <Surfaces>
    <Surface name="Existing ground (3DEP)" desc="{escape(res.layers['dem'].vintage or '3DEP DEM')}; {spacing:.1f} ft grid">
      <Definition surfType="TIN" elevMin="{np.nanmin(zs):.3f}" elevMax="{np.nanmax(zs):.3f}">
        <Pnts>
{pts}
        </Pnts>
        <Faces>
{faces}
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""
    path = out / "surface.xml"
    path.write_text(xml)
    return str(path)


# ----------------------------------------------------------- GIS + KML
def _to_ll(g: BaseGeometry, epsg: int) -> BaseGeometry:
    return reproject(g, epsg, 4326)


def _clean(props: dict) -> dict:
    out = {}
    for k, v in props.items():
        if k.startswith("_") or k in ("Shape__Area", "Shape__Length", "GlobalID"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (np.integer, np.floating)):
            out[k] = v.item()
    return out


def write_gis(res, out: Path) -> dict[str, str]:
    site = res.site
    gdir = out / "gis"
    gdir.mkdir(exist_ok=True)
    layers = {
        "parcel": [(site.parcel.geom, _clean(site.parcel.props))] if site.parcel is not None else [],
        "extent": [(site.clip, {"buffer_ft": site.buffer_ft})],
        "contours": [(f.geom, {"elev": f.props["elev"], "major": f.props["major"], "units": site.units}) for f in res.layers["contours"].features],
        "slope_bands": [(f.geom, {"lo_pct": f.props["lo"], "hi_pct": f.props["hi"]}) for f in res.layers["slope"].features],
    }
    if res.layers.get("roads") is not None and res.layers["roads"].ok():
        layers["roads"] = [(f.geom, {"name": f.props.get("name"), "class": f.props.get("class")}) for f in res.layers["roads"].features]
    if res.layers.get("adjacent") is not None and res.layers["adjacent"].ok():
        layers["adjacent_parcels"] = [(f.geom, {"apn": f.props.get("_APN"), "owner": f.props.get("_OWNER"), "deed": f.props.get("_DEED"),
                                                "plat": f.props.get("_PLAT"), "situs": f.props.get("_SITUS")}) for f in res.layers["adjacent"].features]
    if res.layers.get("row") is not None and res.layers["row"].ok():
        layers["row_approx"] = [(f.geom, {"note": "derived: area between tax parcels"}) for f in res.layers["row"].features]
    for key in ("soils", "flood", "wetland"):
        lr = res.layers.get(key)
        if lr is not None and lr.ok():
            layers[key] = [(f.geom, _clean(f.props)) for f in lr.features]
    bl = res.layers.get("buildings")
    if bl is not None and bl.ok():
        layers["buildings"] = [(f.geom, dict(f.props)) for f in bl.features]
    env = getattr(res, "envelope", None)
    if env:
        layers["zoning_envelope"] = [(env["geom"], {"height_ft": env["height_ft"], "zone": env["zone"], "note": env["label"]})]
    tf = getattr(res, "testfit", None)
    if tf is not None and tf.envelope is not None:
        layers["testfit_buildable"] = [(tf.envelope.building, {"lot_sf": round(tf.envelope.parcel.area)})]
        for n, o in enumerate(tf.options, 1):
            layers[f"testfit_{n}_buildings"] = [(b["geom"], {"stories": b["stories"], "units": b["units"]}) for b in o.buildings]
    written = {}
    for name, feats in layers.items():
        if not feats:
            continue
        fc = {"type": "FeatureCollection",
              "name": name,
              "features": [{"type": "Feature", "properties": p, "geometry": mapping(_to_ll(g, site.epsg))} for g, p in feats if not g.is_empty]}
        path = gdir / f"{name}.geojson"
        path.write_text(json.dumps(fc, separators=(",", ":"), default=str))
        written[f"gis_{name}"] = str(path)
    (gdir / "README.txt").write_text(
        "GeoJSON layers in WGS84 (EPSG:4326), per RFC 7946. Drag into QGIS, ArcGIS Pro, or geojson.io.\n"
        f"The DXF uses {site.crs_label} ({site.units}). Planning-level data only; not a survey.\n")
    return written


def _kml_coords(g, epsg: int) -> list[str]:
    gl = _to_ll(g, epsg)
    if isinstance(gl, (Polygon, MultiPolygon)):
        polys = [gl] if isinstance(gl, Polygon) else list(gl.geoms)
        return ["<Polygon><outerBoundaryIs><LinearRing><coordinates>" + " ".join(f"{x:.7f},{y:.7f}" for x, y in p.exterior.coords) +
                "</coordinates></LinearRing></outerBoundaryIs>" + "".join("<innerBoundaryIs><LinearRing><coordinates>" + " ".join(f"{x:.7f},{y:.7f}" for x, y in r.coords) + "</coordinates></LinearRing></innerBoundaryIs>" for r in p.interiors) +
                "</Polygon>" for p in polys]
    if gl.geom_type == "LineString":
        return ["<LineString><tessellate>1</tessellate><coordinates>" + " ".join(f"{x:.7f},{y:.7f}" for x, y in gl.coords) + "</coordinates></LineString>"]
    return []


def write_kml(res, out: Path) -> str:
    site = res.site
    styles = {"parcel": ("ff2827d6", "00ffffff", 3), "flood": ("ffb4771f", "551f77b4", 1.5), "wetland": ("ff2ca02c", "552ca02c", 1.5), "contour": ("ff2b5a8a", "00ffffff", 1.2),
              "bldg": ("ff8a8a8a", "ccd9d9d9", 1), "envelope": ("ffe08f4d", "554d8fe0", 1.2)}
    head = "".join(f'<Style id="{k}"><LineStyle><color>{lc}</color><width>{w}</width></LineStyle><PolyStyle><color>{pc}</color></PolyStyle></Style>' for k, (lc, pc, w) in styles.items())
    folders = []

    def folder(name, style, geoms_names):
        pm = "".join(f"<Placemark><name>{escape(str(n))}</name><styleUrl>#{style}</styleUrl><MultiGeometry>{''.join(_kml_coords(g, site.epsg))}</MultiGeometry></Placemark>" for g, n in geoms_names if not g.is_empty)
        if pm:
            folders.append(f"<Folder><name>{escape(name)}</name>{pm}</Folder>")

    if site.parcel is not None:
        folder("Tax parcel", "parcel", [(site.parcel.geom, ", ".join(site.parcel_ids) or "Parcel")])
    from .sources.layers import is_sfha

    if res.layers["flood"].ok():
        folder("FEMA flood zones", "flood", [(f.geom, f"Zone {f.props.get('FLD_ZONE')}") for f in res.layers["flood"].features if is_sfha(f.props)])
    if res.layers["wetland"].ok():
        folder("NWI wetlands", "wetland", [(f.geom, f.props.get("ATTRIBUTE")) for f in res.layers["wetland"].features])
    folder("Major contours", "contour", [(f.geom, f"{f.props['elev']:g} ft") for f in res.layers["contours"].features if f.props["major"]])

    def extruded(name, style, items):
        pm = []
        for g, h_ft, label in items:
            gl = _to_ll(g, site.epsg)
            polys = [gl] if isinstance(gl, Polygon) else list(getattr(gl, "geoms", []))
            h_m = h_ft / site.ft_per_m
            body = "".join("<Polygon><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode><outerBoundaryIs><LinearRing><coordinates>"
                           + " ".join(f"{x:.7f},{y:.7f},{h_m:.1f}" for x, y in p.exterior.coords) + "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
                           for p in polys if isinstance(p, Polygon))
            if body:
                pm.append(f"<Placemark><name>{escape(label)}</name><styleUrl>#{style}</styleUrl><MultiGeometry>{body}</MultiGeometry></Placemark>")
        if pm:
            folders.append(f"<Folder><name>{escape(name)}</name>{''.join(pm)}</Folder>")

    bl = res.layers.get("buildings")
    if bl is not None and bl.ok():
        extruded("Existing buildings (3D)", "bldg", [(f.geom, f.props["height_ft"], f"{f.props.get('type') or 'Building'}, {f.props['height_ft']:g} ft") for f in bl.features])
    env = getattr(res, "envelope", None)
    if env:
        extruded("Zoning envelope (3D)", "envelope", [(env["geom"], env["height_ft"], env["label"])])
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{escape(site.matched_address)}</name>
<description>Planning-level data only; not a survey. Sources and dates in provenance.md.</description>{head}{''.join(folders)}</Document></kml>
"""
    path = out / "site.kml"
    path.write_text(kml)
    return str(path)


def write_readme(res, files: dict[str, str]) -> str:
    """Plain-text guide to opening each file, written into every output folder."""
    from .config import DISCLAIMER
    from .crs import wkid_text

    site = res.site
    bx, by = base_point(site.clip)
    have = {k for k in files} | {k for k in res.files}
    lines = [
        f"HOW TO OPEN THESE FILES  ({site.matched_address})",
        "",
        f"Coordinates: {site.crs_label} ({wkid_text(site.epsg)}), {site.units}. Elevations NAVD88, same units.",
        "",
        "AUTOCAD / BRICSCAD / CIVIL 3D",
        "  Open site.dxf directly (File > Open, file type DXF). Keep aerial.png in the same folder: the drawing",
        "  references it as the aerial underlay. Layers are named SITE-* (list in provenance.md).",
    ]
    if "landxml" in have:
        lines += ["  Civil 3D surface: Toolspace > Prospector > Surfaces > Import LandXML > surface.xml."]
    if "dwg" in have:
        lines += ["  site.dwg is an experimental conversion; if AutoCAD complains, use site.dxf."]
    lines += ["", "SKETCHUP"]
    if "terrain_dae" in have:
        lines += ["  3D ground: File > Import, choose 'COLLADA (*.dae)', pick terrain.dae (SketchUp Pro, desktop or web; the",
                  "  free web plan may not allow imports). It's textured with the aerial, has the parcel line draped on it, in feet.",
                  "  Existing buildings come in as grey 3D blocks (and, where zoning rules exist, the zoning envelope as a",
                  "  translucent blue block). Each is its own group, so you can hide or delete it."]
    lines += [f"  Linework (SketchUp Pro): File > Import site-local.dxf, Options > units Feet. It lines up with terrain.dae:",
              f"  both are moved so the base point (E {bx:,.0f}, N {by:,.0f} in State Plane) sits at 0,0."]
    if "terrain_obj" in have:
        lines += ["", "RHINO / BLENDER / 3DS MAX", "  Import terrain.obj (terrain.mtl and terrain_texture.jpg carry the aerial texture)."]
    lines += ["", "QGIS / ARCGIS", "  Drag in the gis/*.geojson layers (WGS84) and dem.tif (elevation, georeferenced)."]
    if "kml" in have:
        lines += ["", "GOOGLE EARTH", "  Open site.kml."]
    lines += ["", "EVERYONE", "  site-summary.pdf: scaled sheets, findings and sources.",
              "  provenance.md: where every layer came from, its date, resolution and known limits.", "", DISCLAIMER, ""]
    path = res.out_dir / "HOW-TO-OPEN.txt"
    path.write_text("\n".join(lines))
    return str(path)


def write_all(res, grid) -> dict[str, str]:
    """Each export is independent: one failing never blocks the others."""
    out = res.out_dir
    files: dict[str, str] = {}
    jobs = [("gis", lambda: write_gis(res, out)), ("kml", lambda: {"kml": write_kml(res, out)})]
    if grid is not None:
        jobs += [("terrain", lambda: write_terrain(res, grid, out)), ("landxml", lambda: {"landxml": write_landxml(res, grid, out)})]
    for name, fn in jobs:
        try:
            files.update(fn())
        except Exception as e:  # noqa: BLE001
            res.flags.append({"level": "missing", "text": f"{name} export failed ({type(e).__name__}: {e}); other files are unaffected."})
    try:
        files["howto"] = write_readme(res, files)
    except Exception as e:  # noqa: BLE001
        print(f"WARN readme failed: {e}", flush=True)
    return files
