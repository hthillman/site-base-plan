"""PDF summary: scaled plan sheets + a findings / sources sheet (11x17)."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["hatch.linewidth"] = 0.6
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import FancyArrow, PathPatch, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from shapely.geometry import MultiPolygon, Polygon  # noqa: E402

from .config import DISCLAIMER, Config  # noqa: E402
from .crs import wkid_text  # noqa: E402

PAGE = (17.0, 11.0)
MAP_BOX = (0.45, 0.45, 11.4, 10.1)  # left, bottom, width, height (inches)
SIDE_X = 12.15
SCALES = [10, 20, 30, 40, 50, 60, 80, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000]

INK = "#1d1d1b"
MUTED = "#6b6b66"
PARCEL = "#d62728"
CONTOUR = "#8a5a2b"
FLOOD = "#1f77b4"
WETLAND = "#2ca02c"
SLOPE_COLORS = ["#a8d5a2", "#f6e27a", "#f4a259", "#d64545", "#7b1e1e"]
HSG_COLORS = {"A": "#e8d8a8", "B": "#d9b77a", "C": "#b98a52", "D": "#7d5a3a"}
FLAG_COLORS = {"alert": "#c62828", "caution": "#ef8f00", "missing": "#6a1b9a", "info": "#455a64"}


def _patch(geom, **kw):
    polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms) if isinstance(geom, MultiPolygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    verts, codes = [], []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            c = np.asarray(ring.coords)
            if len(c) < 3:
                continue
            verts.append(c)
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
    if not verts:
        return None
    return PathPatch(MPath(np.concatenate(verts), codes), **kw)


def _add(ax, geom, **kw):
    p = _patch(geom, **kw)
    if p is not None:
        ax.add_patch(p)


def pick_scale(clip) -> int:
    x0, y0, x1, y1 = clip.bounds
    need = max((x1 - x0) / MAP_BOX[2], (y1 - y0) / MAP_BOX[3])
    return next((s for s in SCALES if s >= need), int(np.ceil(need / 1000) * 1000))


def _map_axes(fig, clip, scale):
    l, b, w, h = MAP_BOX
    ax = fig.add_axes([l / PAGE[0], b / PAGE[1], w / PAGE[0], h / PAGE[1]])
    cx, cy = clip.centroid.x, clip.centroid.y
    ax.set_xlim(cx - w * scale / 2, cx + w * scale / 2)
    ax.set_ylim(cy - h * scale / 2, cy + h * scale / 2)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.8)
        s.set_color(INK)
    return ax


def _scale_bar(ax, scale):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    target = scale * 2  # ~2 inches
    nice = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000]
    length = max(n for n in nice if n <= target) if target >= 5 else 5
    bx, by = x0 + scale * 0.35, y0 + scale * 0.35
    ax.add_patch(Rectangle((bx - scale * 0.15, by - scale * 0.15), length + scale * 0.9, scale * 0.6, facecolor="white", edgecolor="none", alpha=0.85, zorder=20))
    for i in range(4):
        ax.add_patch(Rectangle((bx + i * length / 4, by), length / 4, scale * 0.08, facecolor=INK if i % 2 == 0 else "white", edgecolor=INK, lw=0.6, zorder=21))
    for i, t in enumerate([0, length / 2, length]):
        ax.text(bx + t, by + scale * 0.14, f"{t:g}", ha="center", va="bottom", fontsize=6.5, color=INK, zorder=22)
    ax.text(bx + length + scale * 0.12, by + scale * 0.04, "FT", ha="left", va="center", fontsize=6.5, color=INK, zorder=22)


def _north_arrow(fig, x, y):
    ax = fig.add_axes([x / PAGE[0], y / PAGE[1], 0.6 / PAGE[0], 0.9 / PAGE[1]])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.5)
    ax.axis("off")
    ax.add_patch(FancyArrow(0.5, 0.2, 0, 0.75, width=0.08, head_width=0.4, head_length=0.3, color=INK))
    ax.text(0.5, 1.38, "N", ha="center", va="center", fontsize=12, fontweight="bold", color=INK)
    ax.text(0.5, 0.05, "GRID", ha="center", va="center", fontsize=5.5, color=MUTED)


def _unpublished(site) -> list[str]:
    from .parcel import source_for

    src = source_for(site.state, site.county)
    return src.unpublished() if src is not None and (site.parcel_source or "").startswith(src.name) else []


def _sidebar(fig, res, title, scale, legend: list[tuple], page_no, pages):
    site = res.site
    X = SIDE_X / PAGE[0]

    def t(y, s, **kw):
        fig.text(X, y / PAGE[1], s, **{"fontsize": 8, "color": INK, "va": "top", **kw})

    t(10.55, title, fontsize=15, fontweight="bold")
    t(10.15, "\n".join(textwrap.wrap(site.matched_address, 44)), fontsize=9.5)
    y = 9.55 if len(site.matched_address) <= 44 else 9.38
    meta = [
        f"County: {site.county}",
        f"APN: {', '.join(site.parcel_ids[:3]) or 'NOT RESOLVED'}",
        *([f"Owner of record: {site.parcel.props['_OWNER'][:40]}"] if site.parcel is not None and site.parcel.props.get("_OWNER") else []),
        *([f"Deed: {site.parcel.props['_DEED']}" + (f"   Plat: {site.parcel.props['_PLAT']}" if site.parcel.props.get("_PLAT") else "")]
          if site.parcel is not None and (site.parcel.props.get("_DEED") or site.parcel.props.get("_PLAT")) else []),
        *([f"Not in this parcel data: {', '.join(_unpublished(site))}"] if site.parcel is not None and _unpublished(site) else []),
        f"Buffer: {site.buffer_ft:g} ft around parcel",
        f"Coordinates: {site.crs_label}",
        f"Elevations: {site.units}, NAVD88",
        f"Prepared {date.today().isoformat()} (automated)",
    ]
    for m in meta:
        t(y, m, fontsize=7.5, color=MUTED)
        y -= 0.19

    y -= 0.15
    t(y, "LEGEND", fontsize=8, fontweight="bold")
    y -= 0.28
    for item in legend:
        kind, label, style = item
        ax = fig.add_axes([X, (y - 0.12) / PAGE[1], 0.45 / PAGE[0], 0.16 / PAGE[1]])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        if kind == "line":
            ax.plot([0, 1], [0.5, 0.5], **style)
        else:
            ax.add_patch(Rectangle((0.05, 0.1), 0.9, 0.8, **style))
        fig.text(X + 0.55 / PAGE[0], (y - 0.04) / PAGE[1], label, fontsize=7.5, color=INK, va="center")
        y -= 0.24

    y -= 0.15
    t(y, f'SCALE  1" = {scale}\'', fontsize=9, fontweight="bold")
    t(y - 0.2, f"at {PAGE[0]:g} x {PAGE[1]:g} in. Do not scale if printed smaller.", fontsize=6.5, color=MUTED)
    _north_arrow(fig, SIDE_X + 3.6, y - 0.75)
    y -= 0.55

    # Sources (compact) with status.
    t(y, "DATA SOURCES", fontsize=8, fontweight="bold")
    y -= 0.22
    for lr in res.layers.values():
        if lr.key in ("contours", "slope"):
            continue
        status = {"ok": "", "empty": " (none in extent)", "failed": " FAILED", "skipped": " skipped"}.get(lr.status, "")
        col = FLAG_COLORS["missing"] if lr.status == "failed" else INK
        txt = f"{lr.title}{status}: {lr.vintage or 'vintage not reported'}"
        wrapped = textwrap.wrap(txt, 70)[:3]
        t(y, "\n".join(wrapped), fontsize=6.3, color=col)
        y -= 0.13 * len(wrapped) + 0.07

    # Disclaimer box pinned to the bottom.
    box_h = 1.05
    fig.patches.append(Rectangle((X, 0.45 / PAGE[1]), 4.4 / PAGE[0], box_h / PAGE[1], transform=fig.transFigure, facecolor="#fff4e5", edgecolor=FLAG_COLORS["caution"], lw=0.8))
    fig.text(X + 0.08 / PAGE[0], (0.45 + box_h - 0.08) / PAGE[1], "\n".join(textwrap.wrap(DISCLAIMER, 78)), fontsize=6.4, color=INK, va="top")
    if page_no:
        fig.text((SIDE_X + 4.4) / PAGE[0], 0.25 / PAGE[1], f"Sheet {page_no} of {pages}", fontsize=7, color=MUTED, ha="right")


def _aerial(ax, res, alpha=0.6):
    ae = res.layers.get("aerial")
    if ae and ae.ok() and ae.extra.get("credit"):
        ax.text(0.995, 0.005, ae.extra["credit"], transform=ax.transAxes, ha="right", va="bottom", fontsize=5.5, color=MUTED, zorder=40,
                bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.8))
    if ae and ae.ok():
        img = np.asarray(ae.extra["image"].convert("L").convert("RGB"))
        ax.imshow(img, extent=(ae.extra["x0"], ae.extra["x1"], ae.extra["y0"], ae.extra["y1"]), alpha=alpha, zorder=0, interpolation="bilinear")


def _contours(ax, res, minor=True, label=True, alpha=1.0):
    for f in res.layers["contours"].features:
        x, y = f.geom.xy
        if f.props["major"]:
            ax.plot(x, y, color=CONTOUR, lw=0.8, alpha=alpha, zorder=5)
        elif minor:
            ax.plot(x, y, color=CONTOUR, lw=0.3, alpha=alpha * 0.85, zorder=5)
    if label:
        for f in res.layers["contours"].features:
            if f.props["major"] and f.geom.length > 120:
                p = f.geom.interpolate(0.5, normalized=True)
                q = f.geom.interpolate(min(f.geom.length, f.geom.length * 0.5 + 5))
                ang = np.degrees(np.arctan2(q.y - p.y, q.x - p.x))
                if ang > 90 or ang < -90:
                    ang += 180
                ax.text(p.x, p.y, f"{f.props['elev']:g}", fontsize=5.5, color=CONTOUR, rotation=ang, ha="center", va="center", zorder=6,
                        bbox=dict(boxstyle="square,pad=0.05", fc="white", ec="none", alpha=0.8))


ROAD = "#7a7a72"
ADJ = "#9a9a92"


def _context(ax, res, scale, labels=True):
    """Right-of-way, neighbouring parcels and named roads."""
    L = res.layers
    row = L.get("row")
    if row is not None and row.ok():
        for f in row.features:
            _add(ax, f.geom, facecolor=matplotlib.colors.to_rgba("#bdbdb5", 0.25), edgecolor="none", hatch="..", zorder=1)
    adj = L.get("adjacent")
    site = res.site
    if adj is not None and adj.ok():
        for f in adj.features:
            _add(ax, f.geom, fill=False, edgecolor=ADJ, lw=0.5, zorder=4)
        if labels and site.parcel is not None:
            near = site.parcel.geom.buffer(max(60.0, scale * 0.8))
            cand = sorted((f for f in adj.features if f.geom.intersects(near)), key=lambda f: f.geom.distance(site.parcel.geom))[:24]
            for f in cand:
                polys = [f.geom] if isinstance(f.geom, Polygon) else [g for g in getattr(f.geom, "geoms", []) if isinstance(g, Polygon)]
                big = max(polys, key=lambda q: q.area, default=None)
                if big is None or big.area < (scale * 0.55) ** 2:
                    continue
                c = big.representative_point()
                lines = [l for l in (f.props.get("_APN"), (f.props.get("_OWNER") or "")[:26], f.props.get("_DEED"), f.props.get("_PLAT")) if l]
                ax.text(c.x, c.y, "\n".join(lines), fontsize=4.6, color="#55554f", ha="center", va="center", zorder=7, linespacing=1.15,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
    bl = L.get("buildings")
    if bl is not None and bl.ok():
        for f in bl.features:
            _add(ax, f.geom, facecolor=matplotlib.colors.to_rgba("#9d9a90", 0.35), edgecolor="#7d7a72", lw=0.35, zorder=3)
    roads = L.get("roads")
    if roads is not None and roads.ok():
        from .export_dxf import _road_label_spots

        for f in roads.features:
            for ln in (list(f.geom.geoms) if hasattr(f.geom, "geoms") else [f.geom]):
                if ln.geom_type == "LineString":
                    x, y = ln.xy
                    ax.plot(x, y, color=ROAD, lw=0.7, linestyle=(0, (10, 3, 2, 3)), zorder=5)
        if labels:
            for name, ln in _road_label_spots(roads.features, scale * 1.6):
                mid = ln.interpolate(0.5, normalized=True)
                q = ln.interpolate(min(ln.length, ln.length * 0.5 + scale * 0.1))
                ang = np.degrees(np.arctan2(q.y - mid.y, q.x - mid.x))
                if ang > 90 or ang < -90:
                    ang += 180
                ax.text(mid.x, mid.y, name.upper(), fontsize=6, color="#3d3d38", rotation=ang, rotation_mode="anchor", ha="center", va="center",
                        fontweight="bold", zorder=8, bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))


def _parcel(ax, res):
    if len(res.site.parcels) > 1:
        for f in res.site.parcels:
            _add(ax, f.geom, fill=False, edgecolor=PARCEL, lw=0.7, linestyle=(0, (4, 2)), zorder=10)
    if res.site.parcel is not None:
        _add(ax, res.site.parcel.geom, fill=False, edgecolor=PARCEL, lw=1.6, linestyle=(0, (8, 2, 2, 2)), zorder=10)
    _add(ax, res.site.clip, fill=False, edgecolor=MUTED, lw=0.6, linestyle="--", zorder=9)


def _missing_stamp(ax, text):
    ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", fontsize=16, color=FLAG_COLORS["missing"],
            bbox=dict(boxstyle="round", fc="white", ec=FLAG_COLORS["missing"]), zorder=30)


def write_pdf(res, cfg: Config, opts) -> Path:
    path = res.out_dir / "site-summary.pdf"
    scale = pick_scale(res.site.clip)
    L = res.layers
    from .plugins import testfit_available

    tf = getattr(res, "testfit", None) if testfit_available() else None
    tf_pages = 0 if tf is None or tf.status == "unsupported" else (1 + len(tf.options) if tf.envelope is not None and tf.options else 1)
    pages = 4 + tf_pages

    with PdfPages(path) as pdf:
        # 1. Base plan
        fig = plt.figure(figsize=PAGE)
        ax = _map_axes(fig, res.site.clip, scale)
        _aerial(ax, res)
        _context(ax, res, scale)
        for key, color in (("flood", FLOOD), ("wetland", WETLAND)):
            if L[key].ok():
                for f in L[key].features:
                    if key == "flood" and not _sfha(f):
                        _add(ax, f.geom, facecolor="none", edgecolor=color, lw=0.5, linestyle=":", zorder=3)
                        continue
                    _add(ax, f.geom, facecolor=matplotlib.colors.to_rgba(color, 0.15), edgecolor=color, lw=0.9, zorder=3, hatch="////" if key == "flood" else "....")
        _contours(ax, res)
        _parcel(ax, res)
        _scale_bar(ax, scale)
        if not L["dem"].ok():
            _missing_stamp(ax, "TOPOGRAPHY FAILED TO LOAD")
        legend = [
            ("line", "Tax parcel (assessor)", dict(color=PARCEL, lw=1.6, linestyle=(0, (8, 2, 2, 2)))),
            ("line", "Data extent", dict(color=MUTED, lw=0.6, linestyle="--")),
            ("line", f"Major contour ({opts.contour_interval * cfg.major_every:g} ft)", dict(color=CONTOUR, lw=0.8)),
            ("line", f"Minor contour ({opts.contour_interval:g} ft)", dict(color=CONTOUR, lw=0.3)),
            ("fill", "FEMA 1% floodplain (SFHA)", dict(facecolor=matplotlib.colors.to_rgba(FLOOD, 0.15), edgecolor=FLOOD, hatch="////")),
            ("line", "FEMA other zone boundary", dict(color=FLOOD, lw=0.5, linestyle=":")),
            ("fill", "NWI wetland / water", dict(facecolor=matplotlib.colors.to_rgba(WETLAND, 0.15), edgecolor=WETLAND, hatch="....")),
            ("line", "Adjacent tax parcels", dict(color=ADJ, lw=0.6)),
            ("line", "Road centerline (TIGER)", dict(color=ROAD, lw=0.8, linestyle=(0, (10, 3, 2, 3)))),
            ("fill", "Approx. right-of-way (between parcels)", dict(facecolor=matplotlib.colors.to_rgba("#bdbdb5", 0.3), edgecolor="none", hatch="..")),
        ]
        if L.get("buildings") is not None and L["buildings"].ok():
            from .massing import building_label

            acc = building_label(res)[1]
            legend.append(("fill", {"local": "Existing building (local outline)", "approximate": "Existing building (approx., machine-traced)",
                                    "rough": "Existing building (rough, FEMA)"}[acc],
                           dict(facecolor=matplotlib.colors.to_rgba("#9d9a90", 0.35), edgecolor="#7d7a72")))
        _sidebar(fig, res, "BASE PLAN", scale, legend, 1, pages)
        pdf.savefig(fig)
        plt.close(fig)

        # 2. Slope
        fig = plt.figure(figsize=PAGE)
        ax = _map_axes(fig, res.site.clip, scale)
        _aerial(ax, res, alpha=0.35)
        bands = cfg.slope_bands()
        for f in L["slope"].features:
            _add(ax, f.geom, facecolor=SLOPE_COLORS[f.props["band"] % len(SLOPE_COLORS)], alpha=0.6, edgecolor="none", zorder=2)
        _contours(ax, res, minor=False, label=True, alpha=0.7)
        _context(ax, res, scale, labels=False)
        _parcel(ax, res)
        _scale_bar(ax, scale)
        if not L["slope"].ok():
            _missing_stamp(ax, "SLOPE ANALYSIS UNAVAILABLE (DEM FAILED)")
        legend = [("fill", f"{lo:g}-{hi:g}% slope" if hi is not None else f"{lo:g}%+ slope", dict(facecolor=SLOPE_COLORS[i % len(SLOPE_COLORS)], alpha=0.7, edgecolor="none")) for i, (lo, hi, *_r) in enumerate(bands)]
        legend += [("line", "Tax parcel (assessor)", dict(color=PARCEL, lw=1.6, linestyle=(0, (8, 2, 2, 2))))]
        _sidebar(fig, res, "SLOPE ANALYSIS", scale, legend, 2, pages)
        pdf.savefig(fig)
        plt.close(fig)

        # 3. Soils
        fig = plt.figure(figsize=PAGE)
        ax = _map_axes(fig, res.site.clip, scale)
        _aerial(ax, res, alpha=0.35)
        units = {}
        if L["soils"].ok():
            for f in L["soils"].features:
                hsg = (f.props.get("hydgrpdcd") or "?")[:1]
                _add(ax, f.geom, facecolor=HSG_COLORS.get(hsg, "#cccccc"), alpha=0.55, edgecolor="#5b4630", lw=0.8, zorder=2)
                polys = [f.geom] if isinstance(f.geom, Polygon) else list(getattr(f.geom, "geoms", []))
                big = max((p for p in polys if isinstance(p, Polygon)), key=lambda p: p.area, default=None)
                if big is not None and big.area > (scale * 0.3) ** 2:
                    c = big.representative_point()
                    ax.text(c.x, c.y, str(f.props.get("musym")), fontsize=8, fontweight="bold", color=INK, ha="center", va="center", zorder=6)
                units[f.props.get("musym")] = f.props
        else:
            _missing_stamp(ax, "SOILS FAILED TO LOAD" if L["soils"].status == "failed" else "NO SSURGO DATA IN EXTENT")
        _parcel(ax, res)
        _scale_bar(ax, scale)
        legend = [("fill", f"Hydrologic group {k}", dict(facecolor=v, alpha=0.7, edgecolor="#5b4630")) for k, v in HSG_COLORS.items()]
        legend += [("line", "Tax parcel (assessor)", dict(color=PARCEL, lw=1.6, linestyle=(0, (8, 2, 2, 2))))]
        _sidebar(fig, res, "SOILS (SSURGO)", scale, legend, 3, pages)
        # Map-unit key under the map's top-left corner.
        if units:
            lines = [f"{k}  {v.get('muname')}  [HSG {v.get('hydgrpdcd') or '-'}, {v.get('drclassdcd') or '-'}, hydric {v.get('hydclprs') or 0}%]" for k, v in sorted(units.items(), key=lambda kv: str(kv[0]))]
            ax.text(0.01, 0.99, "MAP UNITS\n" + "\n".join(lines[:14]), transform=ax.transAxes, fontsize=6.5, va="top", ha="left", color=INK,
                    bbox=dict(boxstyle="square,pad=0.4", fc="white", ec=INK, lw=0.5, alpha=0.92), zorder=25)
        pdf.savefig(fig)
        plt.close(fig)

        if tf is not None:
            from .testfit.export import pdf_pages

            pdf_pages(pdf, res, cfg, opts, start=4, total=pages)

        # Last: findings + sources
        fig = plt.figure(figsize=PAGE)
        _summary_page(fig, res, cfg, opts, pages)
        pdf.savefig(fig)
        plt.close(fig)

        d = pdf.infodict()
        d["Title"] = f"Site base plan - {res.site.matched_address}"
        d["Subject"] = "Planning-level site analysis. Not a survey."
    return path


def _sfha(f) -> bool:
    from .sources.layers import is_sfha

    return is_sfha(f.props)


def _summary_page(fig, res, cfg, opts, pages):
    site = res.site
    W, H = PAGE

    def t(x, y, s, **kw):
        fig.text(x / W, y / H, s, **{"fontsize": 8.5, "color": INK, "va": "top", **kw})

    t(0.6, 10.5, "SITE FINDINGS AND DATA SOURCES", fontsize=16, fontweight="bold")
    t(0.6, 10.1, f"{site.matched_address}   |   {site.county} County   |   APN {', '.join(site.parcel_ids[:3]) or 'not resolved'}", fontsize=10)
    t(0.6, 9.85, f"Geocoded by: {site.geocoder}.  Parcel from: {site.parcel_source or 'NOT RESOLVED'}.  Coordinates: {site.crs_label} ({wkid_text(site.epsg)}).", fontsize=7.5, color=MUTED)

    # Flags (left column)
    y = 9.4
    t(0.6, y, "FLAGS", fontsize=10, fontweight="bold")
    y -= 0.3
    order = {"missing": 0, "alert": 1, "caution": 2, "info": 3}
    for fl in sorted(res.flags, key=lambda f: order.get(f["level"], 9)):
        col = FLAG_COLORS.get(fl["level"], INK)
        lines = textwrap.wrap(fl["text"], 92)
        fig.patches.append(Rectangle((0.6 / W, (y - 0.11) / H), 0.09 / W, 0.09 / H, transform=fig.transFigure, color=col))
        t(0.78, y, fl["level"].upper(), fontsize=6.5, color=col, fontweight="bold")
        t(1.45, y, "\n".join(lines), fontsize=7.8)
        y -= 0.16 * len(lines) + 0.12
        if y < 1.0:
            t(0.6, y, "(more flags in provenance.md)", fontsize=7, color=MUTED)
            break

    # Sources table (right column)
    x = 8.9
    y = 9.4
    t(x, y, "LAYERS: STATUS, RESOLUTION, VINTAGE", fontsize=10, fontweight="bold")
    y -= 0.3
    for lr in res.layers.values():
        col = FLAG_COLORS["missing"] if lr.status == "failed" else INK
        t(x, y, f"{lr.title}", fontsize=8, fontweight="bold", color=col)
        t(x + 5.6, y, lr.status.upper(), fontsize=7, color=col, ha="right", fontweight="bold")
        y -= 0.17
        body = [lr.source]
        if lr.resolution:
            body.append(f"Resolution: {lr.resolution}")
        body.append(f"Vintage: {lr.vintage or 'not reported by source'}")
        if lr.error:
            body.append(f"Error: {lr.error}")
        wrapped = []
        for b in body:
            wrapped += textwrap.wrap(b, 100)
        t(x, y, "\n".join(wrapped), fontsize=6.6, color=MUTED if lr.status != "failed" else col)
        y -= 0.122 * len(wrapped) + 0.14

    fig.patches.append(Rectangle((0.6 / W, 0.4 / H), 15.8 / W, 0.62 / H, transform=fig.transFigure, facecolor="#fff4e5", edgecolor=FLAG_COLORS["caution"], lw=0.8))
    t(0.75, 0.93, "\n".join(textwrap.wrap(DISCLAIMER + " Known limitations for every layer are listed in provenance.md next to this PDF.", 210)), fontsize=7.6)
    fig.text((W - 0.6) / W, 0.25 / H, f"Sheet {pages} of {pages}", fontsize=7, color=MUTED, ha="right")
