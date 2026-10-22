"""DXF writer. One named layer per dataset (names from config/layers.toml).

Coordinates are State Plane feet (US survey or international, per state), so the file drops
straight into a drawing set that uses the same zone. Contours carry their
elevation (LWPOLYLINE elevation property, or true 3D polylines).
"""

from __future__ import annotations

import math
import os
import platform
import shutil
import subprocess
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .config import DISCLAIMER, WATERMARK_LINES, Config
from .crs import wkid_text

DXF_VERSION = "R2013"  # opens in AutoCAD 2013+ and SketchUp Pro's importer


def _polys(g: BaseGeometry) -> list[Polygon]:
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _ensure_layer(doc, name: str, color: int, linetype: str = "CONTINUOUS", description: str = ""):
    if name in doc.layers:
        return
    lt = linetype if linetype in doc.linetypes else "CONTINUOUS"
    layer = doc.layers.add(name, color=color, linetype=lt)
    if description:
        layer.description = description[:255]


def _add_poly(msp, poly: Polygon, layer: str, hatch: bool = False, color: int | None = None, transparency: float = 0.7):
    rings = [poly.exterior, *poly.interiors]
    for ring in rings:
        pts = list(ring.coords)[:-1]
        if len(pts) >= 3:
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    if hatch:
        h = msp.add_hatch(color=color or 256, dxfattribs={"layer": layer})
        h.set_solid_fill(color=color or 7)
        h.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True, flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL)
        for i in poly.interiors:
            h.paths.add_polyline_path(list(i.coords)[:-1], is_closed=True)
        h.transparency = transparency
        if color:
            h.dxf.color = color


def _label(msp, text: str, pt, layer: str, height: float, rotation: float = 0.0):
    t = msp.add_text(text, height=height, rotation=rotation, dxfattribs={"layer": layer, "style": "SITE"})
    t.set_placement((pt[0], pt[1]), align=TextEntityAlignment.MIDDLE_CENTER)


def write_dxf(res, cfg: Config, opts) -> dict[str, str]:
    site, layers, out = res.site, res.layers, res.out_dir
    doc = ezdxf.new(DXF_VERSION, setup=True)
    doc.units = ezdxf.units.FT
    doc.header["$INSUNITS"] = 2  # feet (State Plane values; which foot is noted in SITE-NOTES)
    doc.header["$MEASUREMENT"] = 0
    doc.styles.add("SITE", font="arial.ttf")
    msp = doc.modelspace()

    for st in cfg.layers.values():
        if st.key == "slope" or st.key.startswith("tf_"):
            continue
        _ensure_layer(doc, st.name, st.color, st.linetype, st.description)
    for lo, hi, name, aci in cfg.slope_bands():
        rng = f"{lo:g}-{hi:g}%" if hi is not None else f"{lo:g}%+"
        _ensure_layer(doc, name, aci, "CONTINUOUS", f"Slope band {rng}")

    x0, y0, x1, y1 = site.clip.bounds
    extent = max(x1 - x0, y1 - y0)
    txt_h = max(1.5, round(extent / 250, 1))  # ~ readable at a plot scale fitting the extent

    # Aerial underlay first, so it draws beneath vectors.
    ae = layers.get("aerial")
    if ae and ae.ok():
        img_path = out / "aerial.png"
        img = ae.extra["image"]
        img.save(img_path)
        px = ae.extra["px"]
        (out / "aerial.pgw").write_text(f"{px}\n0\n0\n{-px}\n{ae.extra['x0'] + px / 2}\n{ae.extra['y1'] - px / 2}\n")
        w, h = img.size
        idef = doc.add_image_def(filename="aerial.png", size_in_pixel=(w, h))
        msp.add_image(idef, insert=(ae.extra["x0"], ae.extra["y0"]), size_in_units=(w * px, h * px), dxfattribs={"layer": cfg.layer("aerial").name})
        if ae.extra.get("credit"):
            _label(msp, ae.extra["credit"], (ae.extra["x1"] - w * px * 0.25, ae.extra["y0"] + txt_h), cfg.layer("aerial").name, txt_h * 0.6)

    _add_poly(msp, site.clip, cfg.layer("clip").name)

    # Slope bands (hatched, very transparent) so contours read over them.
    for f in layers["slope"].features:
        lo, hi, name, aci = cfg.slope_bands()[f.props["band"]]
        for p in _polys(f.geom):
            _add_poly(msp, p, name, hatch=True, color=aci, transparency=0.75)

    for f in layers["soils"].features if layers["soils"].ok() else []:
        for p in _polys(f.geom):
            _add_poly(msp, p, cfg.layer("soils").name)
        big = max(_polys(f.geom), key=lambda p: p.area, default=None)
        if big is not None and big.area > (txt_h * 6) ** 2:
            c = big.representative_point()
            _label(msp, str(f.props.get("musym") or ""), (c.x, c.y), cfg.layer("soils_label").name, txt_h * 1.2)

    for key, lab in (("flood", "flood_label"), ("wetland", "wetland_label")):
        lr = layers[key]
        if not lr.ok():
            continue
        st = cfg.layer(key)
        for f in lr.features:
            for p in _polys(f.geom):
                _add_poly(msp, p, st.name, hatch=True, color=st.color, transparency=0.6)
            big = max(_polys(f.geom), key=lambda p: p.area, default=None)
            if big is not None and big.area > (txt_h * 8) ** 2:
                c = big.representative_point()
                text = f.props.get("FLD_ZONE") if key == "flood" else f.props.get("ATTRIBUTE")
                if key == "flood" and (f.props.get("STATIC_BFE") or -9999) > -9000:
                    text = f"{text} BFE {f.props['STATIC_BFE']:g}"
                _label(msp, f"{'ZONE ' if key == 'flood' else ''}{text}", (c.x, c.y), cfg.layer(lab).name, txt_h * 1.2)

    # Right-of-way (behind), neighbours, roads.
    for f in layers.get("row").features if layers.get("row") and layers["row"].ok() else []:
        for poly in _polys(f.geom):
            _add_poly(msp, poly, cfg.layer("row").name, hatch=True, color=cfg.layer("row").color, transparency=0.7)
    adj = layers.get("adjacent")
    if adj is not None and adj.ok():
        for f in adj.features:
            for poly in _polys(f.geom):
                _add_poly(msp, poly, cfg.layer("parcel_adj").name)
            big = max(_polys(f.geom), key=lambda q: q.area, default=None)
            if big is not None and big.area > (txt_h * 10) ** 2:
                c = big.representative_point()
                lines = [l for l in (f.props.get("_APN"), f.props.get("_OWNER"), f.props.get("_DEED"), f.props.get("_PLAT")) if l]
                if lines:
                    mt = msp.add_mtext("\\P".join(x.replace("\\", "/") for x in lines), dxfattribs={"layer": cfg.layer("parcel_adj_label").name, "style": "SITE", "char_height": txt_h * 0.8})
                    mt.set_location((c.x, c.y), attachment_point=5)
    roads = layers.get("roads")
    if roads is not None and roads.ok():
        for f in roads.features:
            for ln in (list(f.geom.geoms) if hasattr(f.geom, "geoms") else [f.geom]):
                if ln.geom_type == "LineString" and len(ln.coords) > 1:
                    msp.add_lwpolyline(list(ln.coords), dxfattribs={"layer": cfg.layer("road_cl").name})
        for name, ln in _road_label_spots(roads.features, txt_h * 60):
            mid = ln.interpolate(0.5, normalized=True)
            q = ln.interpolate(min(ln.length, ln.length * 0.5 + txt_h * 2))
            ang = math.degrees(math.atan2(q.y - mid.y, q.x - mid.x))
            if ang > 90 or ang < -90:
                ang += 180
            _label(msp, name.upper(), (mid.x, mid.y), cfg.layer("road_label").name, txt_h * 1.1)
            msp[-1].dxf.rotation = ang

    # Contours.
    maj, mnr, lab = cfg.layer("contour_major").name, cfg.layer("contour_minor").name, cfg.layer("contour_label").name
    for f in layers["contours"].features:
        z = f.props["elev"]
        layer = maj if f.props["major"] else mnr
        pts = list(f.geom.coords)
        if cfg.contour_entity == "polyline3d":
            msp.add_polyline3d([(x, y, z) for x, y in pts], dxfattribs={"layer": layer})
        else:
            pl = msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
            pl.dxf.elevation = z
        if f.props["major"] and f.geom.length > txt_h * 30:
            _label_contour(msp, f.geom, z, lab, txt_h)

    if site.parcel is not None:
        if len(site.parcels) > 1:
            for f in site.parcels:
                for p in _polys(f.geom):
                    _add_poly(msp, p, cfg.layer("parcel").name)
            for p in _polys(site.parcel.geom):
                _add_poly(msp, p, cfg.layer("parcel_site").name)
        else:
            for p in _polys(site.parcel.geom):
                _add_poly(msp, p, cfg.layer("parcel").name)

    # Existing building footprints (plan) and 3D massing blocks.
    bl = layers.get("buildings")
    if bl is not None and bl.ok():
        for f in bl.features:
            for p in _polys(f.geom):
                _add_poly(msp, p, cfg.layer("bldg").name)
    from .massing import blocks, mesh

    for blk in blocks(res, getattr(res, "grid", None)):
        verts, tris = mesh(blk)
        if not tris:
            continue
        pf = msp.add_polyface(dxfattribs={"layer": cfg.layer("bldg_mass" if blk.kind == "existing" else "envelope_mass").name})
        pf.append_faces([[verts[i] for i in t] for t in tris])
        pf.optimize()

    from .plugins import testfit_available

    if getattr(res, "testfit", None) is not None and testfit_available():
        from .testfit.export import add_dxf as add_testfit

        add_testfit(doc, msp, res.testfit, cfg, txt_h)

    bx, by = base_point(site.clip)
    _basepoint(msp, bx, by, site, cfg, txt_h)
    _notes(msp, res, cfg, txt_h)
    _watermark(msp, res, cfg)

    dxf_path = out / "site.dxf"
    doc.saveas(dxf_path)
    files = {"dxf": str(dxf_path)}

    # Same drawing shifted so the base point is 0,0. SketchUp (and anything
    # using single-precision geometry) misbehaves a million feet from origin.
    for e in msp:
        try:
            e.translate(-bx, -by, 0)
        except (AttributeError, NotImplementedError, TypeError):
            pass
    doc.header["$INSBASE"] = (0, 0, 0)
    local_path = out / "site-local.dxf"
    doc.saveas(local_path)
    files["dxf_local"] = str(local_path)
    if (out / "aerial.png").exists():
        files["aerial"] = str(out / "aerial.png")
    if opts.dwg:
        for key, path in (("dwg", dxf_path), ("dwg_local", local_path)):
            dwg = to_dwg(path)
            if dwg:
                files[key] = str(dwg)
    return files


def base_point(clip) -> tuple[float, float]:
    """Round-numbered point at the extent's south-west corner (100 ft grid),
    so the offset between site.dxf and site-local.dxf is easy to type."""
    x0, y0, _, _ = clip.bounds
    return math.floor(x0 / 100) * 100, math.floor(y0 / 100) * 100


def _basepoint(msp, bx: float, by: float, site, cfg: Config, txt_h: float):
    layer = cfg.layer("basepoint").name
    msp.add_point((bx, by, 0), dxfattribs={"layer": layer})
    r = txt_h * 3
    msp.add_circle((bx, by), r, dxfattribs={"layer": layer})
    msp.add_line((bx - r * 1.5, by), (bx + r * 1.5, by), dxfattribs={"layer": layer})
    msp.add_line((bx, by - r * 1.5), (bx, by + r * 1.5), dxfattribs={"layer": layer})
    t = msp.add_mtext(
        f"BASE POINT\\PE {bx:,.0f}  N {by:,.0f}\\P{wkid_text(site.epsg)} ({site.units})\\Psite-local.dxf: 0,0",
        dxfattribs={"layer": layer, "style": "SITE", "char_height": txt_h},
    )
    t.dxf.insert = (bx + r * 1.8, by - r * 0.5)


def _road_label_spots(features, min_len: float):
    """One label per road name on its longest piece (pieces shorter than
    min_len aren't labelled)."""
    best = {}
    for f in features:
        name = f.props.get("name")
        if not name:
            continue
        for ln in (list(f.geom.geoms) if hasattr(f.geom, "geoms") else [f.geom]):
            if ln.geom_type == "LineString" and ln.length >= min_len and (name not in best or ln.length > best[name].length):
                best[name] = ln
    return list(best.items())


def _label_contour(msp, line: LineString, z: float, layer: str, txt_h: float):
    for frac in (0.25, 0.75) if line.length > txt_h * 120 else (0.5,):
        d = line.length * frac
        p = line.interpolate(d)
        q = line.interpolate(min(line.length, d + txt_h))
        ang = math.degrees(math.atan2(q.y - p.y, q.x - p.x))
        if ang > 90 or ang < -90:  # keep text upright
            ang += 180
        _label(msp, f"{z:g}", (p.x, p.y), layer, txt_h)
        msp[-1].dxf.rotation = ang


def _watermark(msp, res, cfg: Config):
    """Large red 'NOT A SURVEY / NOT FOR PERMIT SUBMISSION' across the site on the notes layer."""
    x0, y0, x1, y1 = res.site.clip.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = (x1 - x0) / 16
    for i, line in enumerate(WATERMARK_LINES):
        off = (0.75 - 1.5 * i) * h
        _label(msp, line, (cx - off * 0.47, cy + off * 0.88), cfg.layer("notes").name, h, rotation=28)
        msp[-1].dxf.color = 1  # red


def _notes(msp, res, cfg: Config, txt_h: float):
    site = res.site
    x0, y0, x1, y1 = site.clip.bounds
    lines = [
        "SITE CONTEXT - PUBLIC GIS DATA COMPILATION, PLANNING LEVEL. " + " - ".join(WATERMARK_LINES) + ".",
        f"{site.matched_address}",
        f"County: {site.county}   APN: {', '.join(site.parcel_ids) or 'not resolved'}",
        f"Coordinates: {site.crs_label}, {wkid_text(site.epsg)}. Elevations: {site.units} NAVD88.",
        f"site-local.dxf = this drawing moved by (-{base_point(site.clip)[0]:,.0f}, -{base_point(site.clip)[1]:,.0f}); base point at 0,0.",
        "",
        "DATA SOURCES (see provenance.md for dates and limits):",
    ]
    for lr in res.layers.values():
        status = "" if lr.status == "ok" else f" [{lr.status.upper()}]"
        lines.append(f"- {lr.title}{status}: {lr.source}{' | ' + lr.vintage if lr.vintage else ''}")
    bl = res.layers.get("buildings")
    if bl is not None and bl.ok():
        from .massing import building_label

        lines += ["", building_label(res)[2]]
    lines += ["", DISCLAIMER]
    mt = msp.add_mtext("\\P".join(l.replace("\\", "/") for l in lines), dxfattribs={"layer": cfg.layer("notes").name, "style": "SITE", "char_height": txt_h})
    mt.dxf.insert = (x1 + txt_h * 6, y1)
    mt.dxf.width = txt_h * 90


VENDOR_BIN = Path(__file__).resolve().parent / "bin"


def find_oda() -> str | None:
    for c in (
        shutil.which("ODAFileConverter"),
        "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
    ):
        if c and Path(c).exists():
            return c
    return None


def find_libredwg() -> str | None:
    """Bundled Linux build (for the server) first, then whatever is on PATH."""
    bundled = VENDOR_BIN / "dxf2dwg"
    if bundled.exists() and platform.system() == "Linux":
        if not os.access(bundled, os.X_OK):
            # Deploy targets don't always keep the exec bit; copy to /tmp.
            tmp = Path("/tmp/dxf2dwg")
            if not tmp.exists():
                shutil.copy(bundled, tmp)
                tmp.chmod(0o755)
            return str(tmp)
        return str(bundled)
    return shutil.which("dxf2dwg")


def dwg_converter() -> str:
    if find_oda():
        return "ODA File Converter (AutoCAD 2013 DWG)"
    if find_libredwg():
        return "LibreDWG dxf2dwg (R2000 DWG, experimental writer)"
    return "none installed"


def to_dwg(dxf_path: Path) -> Path | None:
    """DXF -> DWG. ODA File Converter if installed (best fidelity), else
    LibreDWG. Returns None if neither is available or conversion fails."""
    out = dxf_path.with_suffix(".dwg")
    oda = find_oda()
    if oda:
        src = dxf_path.parent
        dst = src / "_dwg"
        dst.mkdir(exist_ok=True)
        subprocess.run([oda, str(src), str(dst), "ACAD2013", "DWG", "0", "1", dxf_path.name], check=False, timeout=120, capture_output=True)
        produced = dst / out.name
        if produced.exists():
            produced.replace(out)
        shutil.rmtree(dst, ignore_errors=True)
        if out.exists():
            return out
    lib = find_libredwg()
    if lib:
        subprocess.run([lib, "-y", "--as", "r2000", "-o", str(out), str(dxf_path)], check=False, timeout=120, capture_output=True)
        if out.exists() and out.stat().st_size > 0:
            return out
    return None
