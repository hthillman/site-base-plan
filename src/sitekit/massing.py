"""3D massing: flat-roofed blocks for existing buildings and, where zoning
rules exist, the zoning envelope (buildable area extruded to the height limit).

Blocks sit on the DEM: the base is the lowest ground under the footprint, so a
block never floats on a slope. Heights are planning-level estimates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely import constrained_delaunay_triangles
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

MAX_BLOCKS = 1500


@dataclass
class Block:
    footprint: Polygon
    base_z: float
    top_z: float
    kind: str      # "existing" | "envelope"
    name: str

    @property
    def height(self) -> float:
        return self.top_z - self.base_z


def _polys(g: BaseGeometry) -> list[Polygon]:
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def ground_under(poly: Polygon, grid) -> float | None:
    """Lowest DEM value under a footprint (its vertices and an interior point)."""
    if grid is None:
        return None
    xs, ys = grid.centers()
    pts = list(poly.exterior.coords) + [poly.representative_point().coords[0]]
    vals = []
    for x, y in pts:
        cx = int(round((x - xs[0]) / grid.cell))
        cy = int(round((ys[0] - y) / grid.cell))
        if 0 <= cy < grid.z.shape[0] and 0 <= cx < grid.z.shape[1]:
            z = grid.z[cy, cx]
            if np.isfinite(z):
                vals.append(float(z))
    return min(vals) if vals else None


def blocks(res, grid) -> list[Block]:
    out: list[Block] = []
    lr = res.layers.get("buildings")
    if lr is not None and lr.ok():
        for f in lr.features[:MAX_BLOCKS]:
            for p in _polys(f.geom):
                if p.area < 20:
                    continue
                z0 = ground_under(p, grid)
                if z0 is None:
                    continue
                label = f.props.get("type") or f.props.get("use") or "Building"
                out.append(Block(p, z0, z0 + float(f.props["height_ft"]), "existing", f"{label}, {f.props['height_ft']:g} ft"))
    env = getattr(res, "envelope", None)
    if env:
        for p in _polys(env["geom"]):
            z0 = ground_under(p, grid)
            if z0 is not None and p.area >= 100:
                out.append(Block(p, z0, z0 + float(env["height_ft"]), "envelope", env["label"]))
    return out


def mesh(block: Block, dx: float = 0.0, dy: float = 0.0) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Closed triangle mesh (roof, floor, walls) for one block, shifted by (-dx, -dy)."""
    p = block.footprint.buffer(0)
    if p.is_empty or not isinstance(p, Polygon):
        p = max(_polys(p), key=lambda q: q.area, default=None)
        if p is None:
            return [], []
    verts: list[tuple[float, float, float]] = []
    tris: list[tuple[int, int, int]] = []

    def v(x, y, z):
        verts.append((x - dx, y - dy, z))
        return len(verts) - 1

    for t in constrained_delaunay_triangles(p).geoms:
        (x0, y0), (x1, y1), (x2, y2) = list(t.exterior.coords)[:3]
        ccw = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0) > 0
        a, b, c = (x0, y0), (x1, y1), (x2, y2)
        if not ccw:
            b, c = c, b
        tris.append((v(*a, block.top_z), v(*b, block.top_z), v(*c, block.top_z)))      # roof, facing up
        tris.append((v(*a, block.base_z), v(*c, block.base_z), v(*b, block.base_z)))   # floor, facing down
    for ring in [p.exterior, *p.interiors]:
        cs = list(ring.coords)
        outward = ring.is_ccw if ring is p.exterior else not ring.is_ccw
        for (x0, y0), (x1, y1) in zip(cs[:-1], cs[1:]):
            a, b = v(x0, y0, block.base_z), v(x1, y1, block.base_z)
            c, d = v(x1, y1, block.top_z), v(x0, y0, block.top_z)
            if outward:
                tris += [(a, b, c), (a, c, d)]
            else:
                tris += [(a, c, b), (a, d, c)]
    return verts, tris


def building_label(res) -> tuple[str, str, str]:
    """(group name, accuracy word, one-line note) for the buildings in this plan, so every file says how far to trust them."""
    lr = res.layers.get("buildings")
    q = (lr.extra.get("quality") if lr is not None else None) or "fema"
    if q == "local":
        when = f", {lr.vintage}" if lr.vintage else ""
        return ("Existing buildings (local outlines)", "local",
                f"BUILDINGS: outlines from {lr.source} ({lr.extra.get('method') or 'published by the local government'}{when}). "
                "Heights from the layer where it has them, otherwise matched or assumed (see provenance.md).")
    if q == "microsoft":
        return ("Existing buildings (APPROXIMATE outlines)", "approximate",
                "BUILDINGS: outlines are APPROXIMATE, machine-traced from aerial imagery (Microsoft US Building Footprints). Usually close "
                "to the roof but can be several feet off, simplified, or missing buildings. Not for design or measurement.")
    return ("Existing buildings (ROUGH outlines)", "rough",
            "BUILDINGS: outlines are ROUGH, from FEMA USA Structures (machine-traced from older imagery). Often rotated, mis-sized, "
            "offset or missing. Context only; do not measure from them.")
