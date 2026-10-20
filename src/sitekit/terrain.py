"""Contours and slope bands from the DEM grid (feet, State Plane)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .model import Feature


@dataclass
class Grid:
    z: np.ndarray  # row 0 = north edge
    x0: float      # west edge
    y0: float      # south edge
    cell: float

    @property
    def y1(self) -> float:
        return self.y0 + self.z.shape[0] * self.cell

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        h, w = self.z.shape
        xs = self.x0 + (np.arange(w) + 0.5) * self.cell
        ys = self.y1 - (np.arange(h) + 0.5) * self.cell
        return xs, ys


def _gauss_kernel(sigma: float) -> np.ndarray:
    r = max(1, int(round(3 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    return k / k.sum()


def smooth(z: np.ndarray, sigma_px: float) -> np.ndarray:
    """NaN-aware separable Gaussian."""
    if sigma_px <= 0:
        return z.copy()
    k = _gauss_kernel(sigma_px)
    valid = np.isfinite(z)
    zz = np.where(valid, z, 0.0)
    ww = valid.astype(float)

    def conv(a: np.ndarray) -> np.ndarray:
        pad = len(k) // 2
        a = np.pad(a, pad, mode="edge")
        a = np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 1, a)
        return np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 0, a)

    num, den = conv(zz), conv(ww)
    out = np.where(den > 1e-6, num / np.maximum(den, 1e-6), np.nan)
    out[~valid] = np.nan
    return out


def contour_levels(zmin: float, zmax: float, interval: float) -> np.ndarray:
    lo = np.ceil(zmin / interval) * interval
    hi = np.floor(zmax / interval) * interval
    return np.arange(lo, hi + interval / 2, interval)


def make_contours(grid: Grid, interval: float, major_every: int, clip: BaseGeometry) -> list[Feature]:
    import contourpy

    # Smooth more for tight intervals: 1 ft contours off a 1 m DEM are noisy.
    sigma_ft = {1: 4.5, 2: 4.0, 5: 3.0}.get(int(interval), 3.0)
    zs = smooth(grid.z, sigma_ft / grid.cell)
    xs, ys = grid.centers()
    finite = zs[np.isfinite(zs)]
    if finite.size == 0:
        return []
    gen = contourpy.contour_generator(xs, ys, np.ma.masked_invalid(zs), line_type=contourpy.LineType.Separate)
    major_step = interval * major_every
    out: list[Feature] = []
    simplify_tol = min(0.5, grid.cell / 4)
    for lvl in contour_levels(finite.min(), finite.max(), interval):
        lines = gen.lines(lvl)
        major = abs((lvl / major_step) - round(lvl / major_step)) < 1e-6
        for pts in lines:
            if len(pts) < 2:
                continue
            ls = LineString(pts).simplify(simplify_tol)
            g = ls.intersection(clip)
            if g.is_empty:
                continue
            parts = list(g.geoms) if isinstance(g, MultiLineString) else [g] if g.geom_type == "LineString" else [p for p in getattr(g, "geoms", []) if p.geom_type == "LineString"]
            for p in parts:
                if p.length < grid.cell * 2:
                    continue
                out.append(Feature(p, {"elev": float(round(lvl, 3)), "major": bool(major)}))
    return out


def slope_percent(grid: Grid) -> np.ndarray:
    zs = smooth(grid.z, 1.0)
    dzdy, dzdx = np.gradient(zs, grid.cell)
    return np.hypot(dzdx, dzdy) * 100.0


def _filled_polys(gen, lo: float, hi: float) -> list[Polygon]:
    """contourpy filled band -> shapely polygons (outer ring + holes)."""
    polys = []
    pts_list, offs_list = gen.filled(lo, hi)
    for pts, offs in zip(pts_list, offs_list):
        rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            polys.append(Polygon(rings[0], rings[1:]))
    return polys


def slope_bands(grid: Grid, breaks: list[float], clip: BaseGeometry, min_area_sqft: float = 200.0) -> list[Feature]:
    """Slope classes as polygons via filled contours of the slope surface.
    Pieces and holes under min_area are dropped / filled so the drawing
    stays readable."""
    import contourpy

    s = smooth(slope_percent(grid), 1.0)
    xs, ys = grid.centers()
    gen = contourpy.contour_generator(xs, ys, np.ma.masked_invalid(s), fill_type=contourpy.FillType.OuterOffset)
    top = float(np.nanmax(s)) + 1 if np.isfinite(s).any() else 1e6
    out = []
    for i, lo in enumerate(breaks):
        hi = breaks[i + 1] if i + 1 < len(breaks) else None
        polys = []
        for p in _filled_polys(gen, lo if i else -1.0, hi if hi is not None else max(top, lo + 1)):
            p = p if p.is_valid else p.buffer(0)
            if p.area < min_area_sqft:
                continue
            p = Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area >= min_area_sqft]) if isinstance(p, Polygon) else p
            polys.append(p)
        if not polys:
            continue
        g = unary_union(polys).simplify(grid.cell * 0.4).buffer(0).intersection(clip)
        if g.is_empty:
            continue
        out.append(Feature(g, {"band": i, "lo": lo, "hi": hi}))
    return out


def stats_within(grid: Grid, geom: BaseGeometry, values: np.ndarray | None = None) -> np.ndarray:
    """Grid values (default elevation) whose cell centres fall inside geom."""
    import shapely

    xs, ys = grid.centers()
    X, Y = np.meshgrid(xs, ys)
    m = shapely.contains_xy(geom, X, Y)
    v = grid.z if values is None else values
    sel = v[m]
    return sel[np.isfinite(sel)]


def steep_polygon(grid: Grid, pct: float, min_area_sqft: float = 200.0) -> BaseGeometry | None:
    """Area at or above `pct` slope (for landslide-hazard style rules)."""
    import contourpy

    s = smooth(slope_percent(grid), 1.0)
    if not np.isfinite(s).any() or np.nanmax(s) < pct:
        return None
    xs, ys = grid.centers()
    gen = contourpy.contour_generator(xs, ys, np.ma.masked_invalid(s), fill_type=contourpy.FillType.OuterOffset)
    polys = [p.buffer(0) for p in _filled_polys(gen, pct, float(np.nanmax(s)) + 1) if p.area >= min_area_sqft]
    return unary_union(polys) if polys else None
