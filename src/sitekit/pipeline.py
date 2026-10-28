"""Base plan end to end: address/APN -> site -> layers -> DXF + PDF + provenance."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
from shapely.geometry import Point, box

from . import crs as crs_mod
from .config import NO_BOUNDARY_STATES, Config, load_config
from .geocode import STATES as STATE_NAMES
from .geocode import GeocodeError, geocode
from .model import Feature, LayerResult, Site, now_iso
from .parcel import looks_like_apn, parcel_at_point, parcel_by_apn, parcel_by_situs, source_for
from .sources import layers as L
from .terrain import Grid, make_contours, slope_bands, slope_percent, stats_within

ASSUMED_EXTENT_FT = 150.0
MAX_PARCELS = 5
MAX_COMBINED_ACRES = 20.0
ZONING_BUDGET_S = 25  # the zoning lookup runs alongside the layer fetch; past this the plan finishes without it
FETCH_BUDGET_S = 60  # all layers fetch in parallel; slow sources past this are flagged as missing  # half-width of the box used when no parcel resolves

Log = Callable[[str], None]


@dataclass
class Options:
    buffer_ft: float = 100.0
    contour_interval: float = 2.0
    county: str | None = None
    state: str | None = None   # two-letter code; required for parcel numbers outside WA
    epsg: int | None = None
    layers_file: str | None = None
    dem_cell_ft: float = 3.0
    out_dir: str = "out"
    dwg: bool = False   # DWG via ODA File Converter / LibreDWG if installed; off by default (DXF opens in AutoCAD)
    testfit: bool = True
    extra_queries: list = field(default_factory=list)   # more addresses / APNs to combine into one site
    layer_preset: str = "default"                       # default | ncs
    layer_custom: dict = field(default_factory=dict)    # {"SITE-PARCEL": "L-PROP-LINE", ...}
    skip: set = field(default_factory=set)              # optional layers left out: aerial, soils, flood, wetland, massing
    firm: dict | None = None    # title block: {name, lines: [..], prepared_by, project, logo: local image path}


@dataclass
class RunResult:
    site: Site
    layers: dict[str, LayerResult]
    flags: list[dict]
    out_dir: Path
    files: dict[str, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    testfit: object = None
    zoning: dict | None = None  # free zoning lookup summary, where covered
    facts: list = field(default_factory=list)  # at-a-glance summary for the results page
    envelope: dict | None = None  # zoning envelope for massing: {geom, height_ft, zone, label}



def approx_sqft(a: float) -> str:
    """GIS areas aren't measured: round to 2-3 significant figures (3,618 -> 3,600; 55,508 -> 55,500)."""
    step = 10 if a < 1000 else 100 if a < 100_000 else 1000
    return f"{round(a / step) * step:,.0f}"

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "site"


def _apn_miss_message(q: str, state: str, county: str | None, defaulted: bool, errs: list[str]) -> str:
    """A parcel number that didn't match: say where we looked, what numbers there look like, and what to try instead."""
    import re as _re

    from .geocode import STATES
    from .parcel import county_coverage, source_for

    name = STATES.get(state, state)
    src = source_for(state, county)
    parts = [f"Parcel number {q} wasn't found in {name}" + (f" ({county} County)" if county else "") + "."]
    if defaulted:
        parts.append("Parcel numbers are searched in Washington unless you pick a state under Change.")
    elif src is None and county_coverage(state) and not county:
        parts.append(f"{name} parcels come from county layers, so add the county under Change.")
    elif src is None:
        parts.append(f"There's no free parcel layer for {name} yet, so search by street address instead.")
    if src is not None:
        ex = _re.findall(r"'([^']{3,40})'", (src.verified or {}).get("apn_test", "") or "")
        if ex:
            parts.append(f"Numbers there look like {ex[0]}.")
    parts.append("Or search the street address, or pick the site on the map below.")
    return " ".join(parts)


def resolve_site(query: str, opts: Options, log: Log) -> Site:
    from .parcel import county_at, source_for

    warnings: list[str] = []
    q = query.strip()
    parcel: Feature | None = None
    parcel_source = ""
    ids: list[str] = []
    county = opts.county
    state = (opts.state or "").upper() or None
    lon = lat = None
    matched = q
    geocoder = ""
    work_sr = 4326  # query parcels in lon/lat until the zone is known

    if looks_like_apn(q):
        defaulted = not state
        state = state or "WA"
        log(f"Looking up parcel number {q} in {state}")
        feats, parcel_source, errs = parcel_by_apn(q, work_sr, state, county)
        if not feats:
            raise GeocodeError(_apn_miss_message(q, state, county, defaulted, errs), hint="apn_not_found")
        counties = {f.props.get("_COUNTY") for f in feats} - {"", None}
        if len(counties) > 1 and not county:
            raise GeocodeError(f"Parcel number {q} exists in several {state} counties ({', '.join(sorted(counties))}); pick the county.", hint="apn_ambiguous")
        biggest = max(feats, key=lambda f: f.geom.area)
        # Parcel numbers are often only unique within a town or county. If the
        # matches are far apart they're different parcels: don't guess.
        from shapely.geometry import MultiPoint

        cents = MultiPoint([f.geom.centroid for f in feats])
        x0, y0, x1, y1 = cents.bounds
        if len(feats) > 1 and max(x1 - x0, y1 - y0) > 0.03:  # ~2-3 km in degrees
            towns = sorted({f.props.get("_CITY") or f.props.get("_COUNTY") or "?" for f in feats})
            raise GeocodeError(f"Parcel number {q} matches {len(feats)} different parcels in {state} ({', '.join(towns[:8])}). "
                               "Enter the street address instead, or add the county.", hint="apn_ambiguous")
        same = [f for f in feats if f.props.get("_COUNTY") == biggest.props.get("_COUNTY")]
        if len(same) > 1:
            # One tax parcel can be stored as several polygons; merge them.
            from shapely.ops import unary_union

            parcel = Feature(unary_union([f.geom for f in same]), biggest.props)
            warnings.append(f"Parcel {q} is stored as {len(same)} separate polygons in the assessor data; they were merged.")
        else:
            parcel = biggest
        ids = sorted({f.props.get("_APN") for f in feats} - {"", None})
        c = parcel.geom.representative_point()
        lon, lat = c.x, c.y
        county = county or parcel.props.get("_COUNTY") or county_at(lon, lat)
        sa = parcel.props.get("_SITUS")
        matched = f"APN {q}" + (f" ({sa}{', ' + parcel.props['_CITY'] if parcel.props.get('_CITY') else ''}, {state})" if sa else f", {state}")
        geocoder = "parcel number lookup"
    else:
        log(f"Geocoding {q}")
        try:
            hit, errs = geocode(q, state)
            lon, lat, matched, geocoder = hit.lon, hit.lat, hit.matched, hit.source
            if "place name" in geocoder:
                typed = re.sub(r"\s+", " ", q).strip()  # not Esri's name: outputs keep what the user typed
                warnings.append(f"'{typed}' was matched as a place name, not a street address. Check that the parcel shown is the one you meant.")
            if hit.source.startswith("Esri"):
                # Esri's terms allow free geocoding when results aren't stored, so
                # saved outputs show the address as entered, not Esri's match.
                matched = re.sub(r"\s+", " ", q).strip()
            county = county or hit.county
            state = hit.state
        except GeocodeError as e:
            feats = parcel_by_situs(q, work_sr, state, county) if state else []
            if not feats:
                raise
            log("Geocoders missed; matched the assessor situs address")
            warnings.append(f"Address matched by assessor situs search, not a geocoder ({e}).")
            parcel = feats[0]
            parcel_source = source_for(state, county).label + " (situs address match)"
            c = parcel.geom.representative_point()
            lon, lat = c.x, c.y
            matched = f"{parcel.props.get('_SITUS')}, {parcel.props.get('_CITY')}, {state}"
            county = parcel.props.get("_COUNTY") or county_at(lon, lat)
            geocoder = "assessor situs address"
            ids = [parcel.props.get("_APN")]

    zone = crs_mod.zone_for_point(lon, lat, state, county)
    epsg = opts.epsg or zone.code
    if opts.epsg:
        zone = crs_mod.Zone(epsg, crs_mod.crs_label(epsg), crs_mod.crs_label(epsg), crs_mod.unit_label(epsg), state or "")

    if parcel is None:
        log("Resolving parcel polygon")
        parcel, parcel_source, ids, errs = parcel_at_point(lon, lat, epsg, state, county)
        src_here = source_for(state, county)
        if parcel is None and src_here is not None and src_here.covers_county(county) is not False:
            warnings += errs  # a known coverage gap gets its own plain message below
    else:
        parcel = Feature(crs_mod.reproject(parcel.geom, work_sr, epsg), parcel.props)

    if parcel is not None and not county:
        county = parcel.props.get("_COUNTY") or None
    county = county or county_at(lon, lat)
    if parcel is not None and len(ids) > 1:
        warnings.append(f"{len(ids)} tax parcels share this location (condo or stacked parcels): {', '.join(ids[:6])}")

    if parcel is None:
        from .geocode import STATES

        from .parcel import county_coverage

        if source_for(state, county) is None:
            have = county_coverage(state)
            where = (f"{county} County, {state} isn't covered yet (county parcel layers so far: {', '.join(have)})" if have
                     else f"{STATES.get(state or '', 'this state')} doesn't publish a free statewide parcel layer")
            warnings.append(
                f"No parcel line: {where}, so the plan covers a {2 * ASSUMED_EXTENT_FT:.0f} ft square around the address. "
                "Get the boundary from the county assessor.")
        else:
            src = source_for(state, county)
            covered = src.covers_county(county)
            if covered is False:
                # A known gap in a partial statewide layer: expected, not an error.
                warnings.append(
                    f"No parcel line: {county} County isn't included in {STATES.get(state or '', state)}'s statewide parcel layer "
                    f"({src.coverage.split('.')[0]}), so the plan covers a {2 * ASSUMED_EXTENT_FT:.0f} ft square around the address. "
                    "Get the boundary from the county assessor.")
            else:
                partial = f" (this layer is partial: {src.coverage.split(';')[0][:120]})" if src.partial else ""
                warnings.append(
                    f"NO PARCEL FOUND at this address in the {state} parcel layer{partial}. Using a {2 * ASSUMED_EXTENT_FT:.0f} ft square "
                    "around the address instead; get the boundary from the county assessor.")
        pt = crs_mod.reproject(Point(lon, lat), 4326, epsg)
        core = box(pt.x - ASSUMED_EXTENT_FT, pt.y - ASSUMED_EXTENT_FT, pt.x + ASSUMED_EXTENT_FT, pt.y + ASSUMED_EXTENT_FT)
    else:
        core = parcel.geom
    x0, y0, x1, y1 = core.bounds
    b = opts.buffer_ft
    clip = box(x0 - b, y0 - b, x1 + b, y1 + b)

    return Site(
        query=q, matched_address=matched, lon=lon, lat=lat, county=county or "unknown",
        epsg=epsg, crs_label=zone.label, parcel=parcel, parcel_source=parcel_source,
        parcel_ids=[i for i in ids if i], clip=clip, buffer_ft=b, geocoder=geocoder, warnings=warnings,
        state=state or "", units=zone.unit, ft_per_m=crs_mod.ft_per_m(epsg),
    )


def combine_sites(primary: Site, extra_queries: list[str], opts: "Options", log: Log) -> Site:
    """Resolve each extra address/APN and merge them with the primary site
    into one multi-parcel site (an assemblage)."""
    from dataclasses import replace

    from shapely.ops import unary_union

    queries = [q.strip() for q in extra_queries if q and q.strip()]
    if not queries:
        return primary
    if 1 + len(queries) > MAX_PARCELS:
        raise GeocodeError(f"Up to {MAX_PARCELS} parcels per site.", hint="multi_limit")
    if primary.parcel is None:
        # Combining needs parcel lines. Rather than fail, build the plan for the first address and say why the rest
        # were left out (people retried the same multi-parcel site a dozen times when this was an error).
        from .parcel import source_for

        where = f"{primary.county} County, {primary.state}" if primary.county and primary.county != "unknown" else primary.state
        why = (f"no parcel line was found at '{primary.query}'" if source_for(primary.state, primary.county)
               else f"Basesheet doesn't have parcel lines for {where} yet (see Parcel data by state)")
        left = ", ".join(f"'{q}'" for q in queries)
        return replace(primary, warnings=list(primary.warnings) + [
            f"Parcels weren't combined: combining needs a parcel line for each address, and {why}. "
            f"This plan covers only '{primary.query}'; {left} {'was' if len(queries) == 1 else 'were'} left out. "
            "Widen the buffer to take in the neighboring land instead."])
    parcels = [primary.parcel]
    labels = [primary.matched_address]
    warnings = list(primary.warnings)
    for q in queries:
        log(f"Adding parcel: {q}")
        try:
            sub = resolve_site(q, replace(opts, state=opts.state or primary.state, buffer_ft=0, extra_queries=[]), lambda m: None)
        except GeocodeError as e:  # say which of the combined addresses failed; the first one already worked
            raise GeocodeError(f"Couldn't find '{q}', one of the parcels to combine. Check the spelling and include the city "
                               "and state, or remove it and build the rest.", hint="multi_missing") from e
        if sub.parcel is None:
            raise GeocodeError(f"Couldn't find a parcel line for '{q}', so it can't be combined. Check the address or parcel number, "
                               "or remove it and build the rest.", hint="multi_missing")
        geom = crs_mod.reproject(sub.parcel.geom, sub.epsg, primary.epsg)
        if any(geom.equals_exact(p.geom, 0.5) or geom.intersection(p.geom).area > 0.9 * geom.area for p in parcels):
            warnings.append(f"'{q}' is the same parcel as one already in the site; skipped.")
            continue
        parcels.append(Feature(geom, sub.parcel.props))
        labels.append(sub.matched_address)
    union = unary_union([p.geom for p in parcels])
    acres = union.area / 43560
    if acres > MAX_COMBINED_ACRES:
        raise GeocodeError(f"Combined site is {acres:.1f} acres; the limit is {MAX_COMBINED_ACRES:g} acres per run.", hint="multi_too_big")
    if union.geom_type != "Polygon":
        warnings.append(f"The {len(parcels)} parcels don't all touch; the site is drawn as separate pieces.")
    def joined(key):
        vals = []
        for p in parcels:
            v = p.props.get(key)
            if v and v not in vals:
                vals.append(v)
        return "; ".join(vals)
    props = {**primary.parcel.props, "_APN": joined("_APN"), "_OWNER": joined("_OWNER"), "_DEED": joined("_DEED"),
             "_PLAT": joined("_PLAT"), "_SUBDIV": joined("_SUBDIV")}
    x0, y0, x1, y1 = union.bounds
    b = opts.buffer_ft
    ids = []
    for p in parcels:
        if p.props.get("_APN") and p.props["_APN"] not in ids:
            ids.append(p.props["_APN"])
    warnings.append(f"Combined site: {len(parcels)} parcels, {union.area:,.0f} sq ft ({acres:.2f} ac).")
    return replace(primary, parcel=Feature(union, props), parcels=parcels, parcel_ids=ids,
                   matched_address=" + ".join(labels), clip=box(x0 - b, y0 - b, x1 + b, y1 + b), warnings=warnings)


def _parcel_layer(site: Site) -> LayerResult:
    from .parcel import source_for

    src = source_for(site.state, site.county)
    from_state = src is not None and src.name in (site.parcel_source or "")
    r = LayerResult(
        key="parcel", title="Tax parcel", source=site.parcel_source or "not resolved",
        url=src.url if from_state else "",
        resolution="Assessor tax-lot mapping; typical positional error 5-50 ft, worse in rural areas",
        vintage=(src.vintage if from_state else ""),
        limitations=[
            "Assessor parcels are for taxation, not legal boundary location.",
            "Does not show easements, rights-of-way, setbacks, or zoning.",
        ] + ([f"Statewide coverage: {src.coverage}"] if from_state and src.coverage else [])
          + ([f"Terms of use: {src.terms}"] if from_state and src.terms else []),
        retrieved_at=now_iso(),
    )
    if site.parcel is None and site.state in NO_BOUNDARY_STATES:
        r.status = "skipped"
        r.error = f"Not drawn in {STATE_NAMES.get(site.state, site.state)} (see the note on this plan)."
    elif site.parcel is None and src is None:
        r.status = "skipped"
        r.error = f"No free statewide parcel layer for {site.state or 'this state'} yet; boundary not drawn."
    elif site.parcel is None and src.covers_county(site.county) is False:
        r.status = "skipped"
        r.error = f"{site.county} County isn't included in this layer ({src.coverage.split('.')[0]}); boundary not drawn."
    elif site.parcel is None:
        r.status = "failed"
        r.error = "; ".join(w for w in site.warnings if "parcel" in w.lower()) or "no parcel found"
    else:
        r.status = "ok"
        r.features = [site.parcel]
    return r


class Findings(list):
    """Plain-language flags, plus `facts`: the at-a-glance summary for the results page
    ({key, label, value, sub, tone}; tone ok | warn | alert | info | missing)."""

    def __init__(self):
        super().__init__()
        self.facts: list[dict] = []

    def fact(self, key: str, label: str, value: str, sub: str = "", tone: str = "info") -> None:
        self.facts.append({"key": key, "label": label, "value": value, "sub": sub, "tone": tone})


def compute_flags(site: Site, layers: dict[str, LayerResult], grid: Grid | None, slope: np.ndarray | None, cfg: Config) -> list[dict]:
    """Plain-language findings. level: alert | caution | info | missing."""
    flags = Findings()
    parcel = site.parcel.geom if site.parcel else None
    area_ref = parcel if parcel is not None else site.clip
    where = "parcel" if parcel is not None else "assumed site extent"

    def add(level: str, text: str):
        flags.append({"level": level, "text": text})

    for w in site.warnings:
        add("alert" if "NO PARCEL FOUND" in w else "info" if w.startswith("Combined site:") else "caution", w)

    if parcel is not None:
        add("info", f"Parcel area about {approx_sqft(parcel.area)} sq ft ({parcel.area / 43560:.2f} ac) from assessor GIS lines, not a surveyed area.")
        flags.fact("parcel", "Parcel", f"≈{parcel.area / 43560:.2f} ac", f"≈{approx_sqft(parcel.area)} sq ft · assessor GIS, not surveyed", "info")
        pp = site.parcel.props
        rec = [x for x in (f"owner of record {pp['_OWNER']}" if pp.get("_OWNER") else "", pp.get("_DEED"), f"plat {pp['_PLAT']}" if pp.get("_PLAT") else "",
                           f"subdivision {pp['_SUBDIV']}" if pp.get("_SUBDIV") else "") if x]
        src_rec = source_for(site.state, site.county)
        missing = src_rec.unpublished() if src_rec is not None and site.parcel_source.startswith(src_rec.name) else []
        note = f" Not published in this parcel data: {', '.join(missing)}." if missing else ""
        if rec or note:
            add("info", ("Assessor record: " + "; ".join(rec) + "." if rec else "Assessor record:") + note)
    elif site.state in NO_BOUNDARY_STATES:
        flags.fact("parcel", "Parcel", "Not drawn", f"Property lines aren't shown in {STATE_NAMES.get(site.state, site.state)}", "info")
    else:
        flags.fact("parcel", "Parcel", "No parcel line", "Plan drawn around the address", "warn")

    fl = layers.get("flood")
    if fl and fl.status in ("ok", "empty"):
        sf = [f for f in fl.features if L.is_sfha(f.props)]
        hit = [f for f in sf if f.geom.intersects(area_ref)]
        if hit:
            zones = sorted({f.props.get("FLD_ZONE") for f in hit})
            a = sum(f.geom.intersection(area_ref).area for f in hit)
            bfe = sorted({f.props.get("STATIC_BFE") for f in hit if (f.props.get("STATIC_BFE") or -9999) > -9000})
            txt = f"{where.capitalize()} intersects the mapped 1%-annual-chance floodplain (FEMA Zone {', '.join(zones)}): about {a:,.0f} sq ft ({a / area_ref.area:.0%} of {where})."
            if bfe:
                txt += f" Static BFE {', '.join(f'{v:g}' for v in bfe)} ft."
            add("alert", txt)
            flags.fact("flood", "Flood zone", f"In floodplain", f"Zone {', '.join(zones)} · {a / area_ref.area:.0%} of {where}", "alert")
        elif sf:
            flags.fact("flood", "Flood zone", "Nearby", f"Zone {', '.join(sorted({f.props.get('FLD_ZONE') for f in sf}))} within {site.buffer_ft:.0f} ft", "warn")
            add("caution", f"Mapped floodplain (Zone {', '.join(sorted({f.props.get('FLD_ZONE') for f in sf}))}) lies within {site.buffer_ft:.0f} ft of the {where}, but not on it.")
        else:
            zones = sorted({f.props.get("FLD_ZONE") for f in fl.features if f.geom.intersects(area_ref)})
            if zones:
                add("info", f"No mapped Special Flood Hazard Area on the {where} (FEMA Zone {', '.join(z for z in zones if z)}).")
                flags.fact("flood", "Flood zone", "Not in floodplain", f"FEMA Zone {', '.join(z for z in zones if z)}", "ok")
            elif fl.extra.get("fallback"):
                flags.fact("flood", "Flood zone", "Not in floodplain", "From a copy of FEMA's map; confirm", "ok")
                add("info", f"No mapped 1% or 0.2% annual chance flood zone on the {where}, per Esri's copy of FEMA's map (FEMA's own service didn't respond). Confirm at msc.fema.gov.")
            else:
                flags.fact("flood", "Flood zone", "Not mapped", "Unmapped isn't the same as no risk", "warn")
                add("caution", "FEMA has no digital flood zone polygons here. Unmapped is not the same as no flood risk.")

    wl = layers.get("wetland")
    if wl and wl.status in ("ok", "empty"):
        hit = [f for f in wl.features if f.geom.intersects(area_ref)]
        if hit:
            types = sorted({f.props.get("WETLAND_TYPE") for f in hit if f.props.get("WETLAND_TYPE")})
            a = sum(f.geom.intersection(area_ref).area for f in hit)
            flags.fact("wetland", "Wetlands", "On the parcel" if parcel is not None else "On the site", f"{', '.join(types)} · about {a:,.0f} sq ft", "alert")
            add("alert", f"{where.capitalize()} intersects NWI-mapped wetland or water ({', '.join(types)}), about {a:,.0f} sq ft. County critical-areas buffers likely apply; a wetland delineation is needed.")
        elif wl.features:
            types = sorted({f.props.get("WETLAND_TYPE") for f in wl.features if f.props.get("WETLAND_TYPE")})
            flags.fact("wetland", "Wetlands", "Nearby", f"Within {site.buffer_ft:.0f} ft · buffers may reach the {where}", "warn")
            add("caution", f"NWI wetland/water mapped within {site.buffer_ft:.0f} ft ({', '.join(types)}). Regulatory buffers can extend onto the {where}.")
        else:
            add("info", "No NWI wetlands mapped in the extent. NWI misses many small and forested wetlands.")
            flags.fact("wetland", "Wetlands", "None mapped", "NWI misses small wetlands", "ok")

    if grid is not None and slope is not None:
        z = stats_within(grid, area_ref)
        if z.size:
            add("info", f"Elevation on {where}: {z.min():,.1f} to {z.max():,.1f} ft NAVD88 (relief {z.max() - z.min():,.1f} ft).")
            flags.fact("elev", "Elevation", f"≈{z.min():,.0f} to {z.max():,.0f} ft", f"{z.max() - z.min():,.1f} ft of relief · USGS data, NAVD88", "info")
        s = stats_within(grid, area_ref, slope)
        if s.size:
            steep_break = cfg.slope_breaks[-1]
            mid_break = cfg.slope_breaks[-2] if len(cfg.slope_breaks) > 1 else None
            steep = float((s >= steep_break).mean())
            mid = float(((s >= mid_break) & (s < steep_break)).mean()) if mid_break is not None else 0
            if steep >= 0.02:
                add("alert" if steep >= 0.10 else "caution", f"{steep:.0%} of the {where} is {steep_break:g}%+ slope. Many jurisdictions regulate slopes of 40%+ (and often 15-40%) as geologic hazard areas; check the local critical-areas or steep-slope code.")
            if mid >= 0.05:
                add("caution", f"{mid:.0%} of the {where} is {mid_break:g}-{steep_break:g}% slope.")
            add("info", f"Median slope on {where} {np.median(s):.1f}%.")
            flags.fact("slope", "Slope", f"{np.median(s):.1f}% median",
                       f"{steep:.0%} over {steep_break:g}%" if steep >= 0.02 else f"Mostly under {mid_break:g}%" if mid_break is not None and mid < 0.05 else f"{mid:.0%} at {mid_break:g}-{steep_break:g}%",
                       "alert" if steep >= 0.10 else "warn" if steep >= 0.02 or mid >= 0.05 else "ok")

    so = layers.get("soils")
    if so and so.ok():
        on = [f for f in so.features if f.geom.intersects(area_ref)]
        hydric = [f for f in on if (f.props.get("hydclprs") or 0) and float(f.props["hydclprs"]) >= 50]
        if hydric:
            names = sorted({f.props.get("muname") for f in hydric})
            add("caution", f"Hydric soils mapped on the {where} ({'; '.join(names)}), a common wetland indicator.")
        dgroup = sorted({f.props.get("muname") for f in on if (f.props.get("hydgrpdcd") or "").startswith("D")})
        if dgroup:
            add("caution", f"Hydrologic soil group D (slow infiltration) on the {where}: {'; '.join(dgroup)}. Infiltration BMPs may not work.")
        if on:
            major = max(on, key=lambda f: f.geom.intersection(area_ref).area)
            add("info", f"Dominant soil: {major.props.get('musym')} {major.props.get('muname')} (hydrologic group {major.props.get('hydgrpdcd') or 'n/a'}, {major.props.get('drclassdcd') or 'drainage n/a'}).")
            name = str(major.props.get("muname") or "").split(",")[0]
            flags.fact("soil", "Soil", name, f"Hydrologic group {major.props.get('hydgrpdcd') or 'n/a'} · {(major.props.get('drclassdcd') or 'drainage n/a').lower()}",
                       "warn" if hydric or dgroup else "info")

    dem = layers.get("dem")
    if dem and dem.ok():
        srcs = dem.extra.get("lidar") or []
        if srcs:
            try:
                yr = int(str(srcs[0].get("collect_end", ""))[:4])
                if yr < date.today().year - 10:
                    add("caution", f"Primary LiDAR is from {yr}. Grading or slides since then are not shown.")
            except ValueError:
                pass

    src = source_for(site.state, site.county)
    if site.parcel is not None and src is not None and "commercial" in (src.terms or "").lower():
        add("caution", f"Parcel data terms ({src.name}): {src.terms}")

    for key, lr in layers.items():
        if lr.status == "failed":
            add("missing", f"{lr.title}: FAILED TO LOAD ({lr.error}). This layer is missing from all outputs; do not read its absence as 'none present'.")
    return flags


def run(query: str, opts: Options | None = None, log: Log = print) -> RunResult:
    opts = opts or Options()
    cfg = load_config(opts.layers_file)
    from .config import apply_layer_names

    layer_warnings = apply_layer_names(cfg, opts.layer_preset, opts.layer_custom)
    t0 = time.time()
    timings: dict[str, float] = {}

    site = resolve_site(query, opts, log)
    if opts.extra_queries:
        site = combine_sites(site, opts.extra_queries, opts, log)
    timings["resolve"] = time.time() - t0
    log(f"Site: {site.matched_address} | {site.county} County, {site.state} | {site.crs_label}")
    withheld = site.state in NO_BOUNDARY_STATES
    if withheld:  # no property lines, neighbours, buildings or massing here (see config.NO_BOUNDARY_STATES)
        log("Leaving out property lines and buildings in this state")
        site = replace(site, parcel=None, parcels=[], warnings=[NO_BOUNDARY_STATES[site.state]]
                       + [w for w in site.warnings if "parcel" not in w.lower()])
        opts = replace(opts, skip=set(opts.skip) | {"massing", "adjacent"}, testfit=False)

    t1 = time.time()
    from .plugins import testfit_available, zoning_summary

    # The free zoning lookup only needs the site, so it runs while the layers download (a slow city zoning
    # server used to add its full wait after everything else).
    zex = ThreadPoolExecutor(max_workers=1)
    zfut = None if (opts.testfit and testfit_available()) else zex.submit(zoning_summary, site)
    zex.shutdown(wait=False)
    log("Fetching layers in parallel: DEM, imagery, soils, flood, wetlands, buildings")
    jobs = {
        "dem": lambda: L.fetch_dem(site.clip, site.epsg, cell_ft=opts.dem_cell_ft, ft_per_m=site.ft_per_m),
        "aerial": lambda: L.fetch_imagery(site.clip, site.epsg),
        "soils": lambda: L.fetch_soils(site.clip, site.epsg),
        "flood": lambda: L.fetch_flood(site.clip, site.epsg),
        "wetland": lambda: L.fetch_wetlands(site.clip, site.epsg),
        "roads": lambda: L.fetch_roads(site.clip, site.epsg),
        "adjacent": lambda: L.fetch_adjacent(site.clip, site.epsg, source_for(site.state, site.county), site.parcel.geom if site.parcel else None),
        "buildings": lambda: L.fetch_buildings(site.clip, site.epsg, site.ft_per_m, site.state, site.county),
    }
    skip_keys = {("buildings" if k == "massing" else k) for k in opts.skip} & set(jobs)
    jobs = {k: fn for k, fn in jobs.items() if k not in skip_keys}
    # One overall budget: a service that hasn't answered by then is reported
    # as timed out (never silently dropped) and the run finishes without it.
    ex = ThreadPoolExecutor(max_workers=len(jobs))
    futs = {k: ex.submit(fn) for k, fn in jobs.items()}
    deadline = time.time() + FETCH_BUDGET_S
    fetched = {}
    titles = {"dem": "Topography (LiDAR DEM)", "aerial": "Aerial imagery", "soils": "Soils (SSURGO)", "flood": "FEMA flood hazard zones",
              "wetland": "Wetlands (NWI)", "roads": "Road centerlines", "adjacent": "Adjacent parcels",
              "buildings": "Existing buildings"}
    for k, fut in futs.items():
        try:
            fetched[k] = fut.result(timeout=max(0.1, deadline - time.time()))
        except Exception as e:  # noqa: BLE001 - timeout or crash
            lr = LayerResult(k, titles[k], "", "", status="failed", retrieved_at=now_iso())
            lr.error = f"source didn't respond within {FETCH_BUDGET_S} s" if isinstance(e, TimeoutError) or "Timeout" in type(e).__name__ else f"{type(e).__name__}: {e}"
            fetched[k] = lr
    ex.shutdown(wait=False, cancel_futures=True)
    for k in sorted(skip_keys):
        fetched[k] = LayerResult(k, titles[k], "", "", status="skipped", retrieved_at=now_iso(),
                                 error=f"Not drawn in {STATE_NAMES.get(site.state, site.state)} (see the note on this plan)." if withheld and k in ("adjacent", "buildings")
                                 else "Left out: unchecked under Options.")
    for k, lr in fetched.items():
        log(f"  {lr.title}: {lr.status}" + (f" ({lr.error})" if lr.error else f", {len(lr.features)} features" if lr.features else ""))
    timings["fetch"] = time.time() - t1

    layers: dict[str, LayerResult] = {"parcel": _parcel_layer(site)}
    layers.update(fetched)

    # Approximate right-of-way: extent minus every tax parcel, where we have them.
    adj = layers.get("adjacent")
    row = LayerResult("row", "Approximate right-of-way", "Derived: area between tax parcels, where a road centerline runs through it", "",
                      retrieved_at=now_iso(), vintage="Derived from the adjacent parcels and road centerlines above",
                      limitations=["Derived from assessor parcel gaps, not a recorded right-of-way. Verify with plats or a survey.",
                                   "Where parcel data has holes, gaps that aren't right-of-way can show up; pieces without a road centerline are dropped."])
    if adj is not None and adj.ok() and site.parcel is not None:
        parcels = list(adj.extra.get("all_parcels") or []) + [site.parcel.geom]
        roads = [f.geom for f in layers["roads"].features] if layers.get("roads") and layers["roads"].ok() else []
        row.features = L.derive_row(site.clip, parcels, roads)
        row.status = "ok" if row.features else "empty"
    else:
        row.status = "skipped"
        row.error = "Needs parcel data around the site."
    layers["row"] = row

    grid = slope = None
    dem = layers["dem"]
    t2 = time.time()
    floor = dem.extra.get("min_interval_ft", 1.0) if dem.ok() else 1.0
    if dem.ok() and dem.extra.get("fallback"):
        site.warnings.append("USGS's LiDAR elevation service was too slow to answer just now, so this plan's topography comes from a coarser "
                             f"backup (about 10 m), with {max(opts.contour_interval, floor):g} ft contours and heavier lines every "
                             f"{max(opts.contour_interval, floor) * cfg.major_every:g} ft. Build the site again in a few minutes to get LiDAR contours (usually 1 to 2 ft).")
        contour_src = "Derived from backup DEM (AWS Terrain Tiles, about 10 m)"
    else:
        contour_src = "Derived from 3DEP DEM"
        if opts.contour_interval < floor:
            site.warnings.append(f"Contour interval raised from {opts.contour_interval:g} ft to {floor:g} ft: the best elevation data here is "
                                 f"{dem.extra.get('source_res_m'):.1f} m, too coarse for finer contours.")
    opts.contour_interval = max(opts.contour_interval, floor)
    contours = LayerResult("contours", f"Contours ({opts.contour_interval:g} ft)", contour_src, "", retrieved_at=now_iso())
    slopes = LayerResult("slope", "Slope analysis", contour_src, "", retrieved_at=now_iso())
    if dem.ok():
        grid = Grid(dem.extra["z"], dem.extra["x0"], dem.extra["y0"], dem.extra["cell"])
        log(f"Generating {opts.contour_interval:g} ft contours")
        contours.features = make_contours(grid, opts.contour_interval, cfg.major_every, site.clip)
        contours.status = "ok" if contours.features else "empty"
        contours.resolution = f"{opts.contour_interval:g} ft interval, majors every {opts.contour_interval * cfg.major_every:g} ft"
        contours.vintage = dem.vintage
        contours.limitations = ["Generated from a Gaussian-smoothed DEM (sigma about 1.5 cells) and simplified; small grade breaks, curbs and walls are lost."]
        log("Classifying slope bands")
        slope = slope_percent(grid)
        slopes.features = slope_bands(grid, cfg.slope_breaks, site.clip)
        slopes.status = "ok" if slopes.features else "empty"
        slopes.resolution = f"{grid.cell:.1f} ft cells; regions under 200 sq ft merged into neighbours"
        slopes.vintage = dem.vintage
        bands = ", ".join(f"{lo:g}-{hi:g}%" if hi is not None else f"{lo:g}%+" for lo, hi, *_ in cfg.slope_bands())
        slopes.limitations = [f"Bands: {bands}. Slope computed over ~{grid.cell * 2:.0f} ft; short steep banks are averaged down."]
    else:
        for lr in (contours, slopes):
            lr.status = "failed"
            lr.error = "DEM unavailable"
    layers["contours"] = contours
    layers["slope"] = slopes
    timings["terrain"] = time.time() - t2

    flags = compute_flags(site, layers, grid, slope, cfg)
    base_facts = list(flags.facts)  # flags becomes a plain list once zoning/test-fit flags are prepended
    if opts.layer_preset != "default" or opts.layer_custom:
        flags.append({"level": "info", "text": f"CAD layers use {'NCS-style names' if opts.layer_preset == 'ncs' else 'the default names'}"
                      + (" plus your custom mapping" if opts.layer_custom else "") + " (full list in provenance.md)."})
    flags += [{"level": "caution", "text": w} for w in layer_warnings]

    tf = None
    zoning = None
    from .plugins import testfit_available, zoning_envelope, zoning_summary

    if opts.testfit and testfit_available():
        from .testfit.export import flags as tf_flags
        from .testfit.run import run_testfit

        t4 = time.time()
        try:
            tf = run_testfit(site, layers, grid, log)
        except Exception as e:  # noqa: BLE001
            from .testfit.run import TestFit

            tf = TestFit("failed", f"Test fit crashed: {type(e).__name__}: {e}")
        if tf.zoning_layer is not None:
            layers["zoning"] = tf.zoning_layer
        flags = tf_flags(tf) + flags
        timings["testfit"] = time.time() - t4
    else:
        tw = time.time()
        try:
            zflags, zoning = zfut.result(timeout=max(1.0, ZONING_BUDGET_S - (time.time() - t1)))
        except Exception as e:  # noqa: BLE001 - TimeoutError or a crash: the plan finishes without zoning
            timed_out = isinstance(e, TimeoutError) or "Timeout" in type(e).__name__
            zflags, zoning = [{"level": "caution", "kind": "zoning", "text": (
                f"Zoning lookup skipped: the jurisdiction's zoning map didn't answer within {ZONING_BUDGET_S} s. The rest of the plan is complete; "
                "try again later for zoning." if timed_out else f"Zoning lookup failed ({type(e).__name__}); the rest of the plan is unaffected.")}], None
        flags = zflags + flags
        timings["zoning_wait"] = time.time() - tw  # only the time the plan waited for it (it runs alongside the fetch and terrain)

    envelope = None
    if "massing" not in opts.skip and tf is not None and getattr(tf, "envelope", None) is not None and getattr(tf, "rules", None) is not None and tf.rules.get("height", "max_ft"):
        h = tf.rules.get("height", "max_ft").value
        envelope = {"geom": tf.envelope.building, "height_ft": h, "zone": tf.rules.zone,
                    "label": f"Zoning envelope, {tf.rules.zone}: buildable area after setbacks, up to {h:g} ft"}
    elif "massing" not in opts.skip and zoning and zoning.get("details") and any(d.get("facts") for d in zoning["details"]):
        envelope = zoning_envelope(site, layers, grid)
    bl = layers.get("buildings")
    if bl is not None and bl.ok():
        on_site = [f for f in bl.features if site.parcel is not None and f.geom.intersects(site.parcel.geom)]
        where = f" ({len(on_site)} on the parcel)" if site.parcel is not None else ""
        if bl.extra.get("machine") == "microsoft":
            flags.append({"level": "info", "text": f"{len(bl.features)} existing building(s) in the extent{where} are drawn as 3D massing. "
                          "Outlines are Microsoft's machine-traced footprints: usually close to the roof, but simplified and sometimes off or "
                          "missing; use them for context, not as measured outlines. " + " ".join(bl.notes[-1:])})
        elif bl.extra.get("planimetric"):
            flags.append({"level": "info", "text": f"{len(bl.features)} existing building(s) in the extent{where}, outlined from {bl.source} "
                          f"({bl.vintage or 'date not stated'}) and drawn as 3D massing. " + " ".join(bl.notes[-1:])})
        else:
            flags.append({"level": "info", "text": f"{len(bl.features)} existing building(s) in the extent{where} are drawn as 3D massing from "
                          "FEMA USA Structures. These outlines are traced from aerial imagery by machine learning: often a few feet off, "
                          "simplified to boxes, and small or tree-covered buildings can be missing. Use them for context, not as measured outlines."})
    if envelope:
        flags.append({"level": "info", "text": f"{envelope['label']}. Shown as a translucent block in the 3D files; a quick volume check, not a design."})
    facts = base_facts
    if bl is not None and bl.ok():
        q = bl.extra.get("quality")
        facts.append({"key": "buildings", "label": "Buildings", "value": f"{len(bl.features)} in view" + (f", {len(on_site)} on parcel" if site.parcel is not None else ""),
                      "sub": {"local": "Local outlines", "microsoft": "Approximate outlines", "fema": "Rough outlines"}.get(q, ""), "tone": "info"})
    if zoning and zoning.get("details"):
        d0 = zoning["details"][0]
        h = next((f for f in d0.get("facts", []) if f.startswith("height")), "")
        facts.append({"key": "zoning", "label": "Zoning", "value": d0["zone"], "sub": f"{d0['jurisdiction']}" + (f" · {h}" if h else ""), "tone": "info"})

    stamp = date.today().isoformat()
    out = Path(opts.out_dir) / f"{_slug(site.matched_address)}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    res = RunResult(site, layers, flags, out, timings=timings, testfit=tf, zoning=zoning, envelope=envelope, facts=facts)
    res.firm = opts.firm
    res.grid = grid  # DEM, for exporters that place 3D massing on the ground

    from .export_dxf import write_dxf
    from .export_pdf import write_pdf
    from .provenance import write_provenance

    t3 = time.time()
    log("Writing DXF")
    res.files.update(write_dxf(res, cfg, opts))
    log("Writing PDF")
    res.files["pdf"] = str(write_pdf(res, cfg, opts))
    if (out / "preview.png").exists():
        res.files["preview"] = str(out / "preview.png")
    if grid is not None:
        res.files["dem"] = str(_write_dem(out / "dem.tif", grid, site.epsg))
        res.files["dem_tfw"] = str(out / "dem.tfw")
        res.files["dem_prj"] = str(out / "dem.prj")
    from .exports import write_all

    log("Writing terrain mesh, LandXML, GIS and KML")
    res.files.update(write_all(res, grid))
    timings["write"] = time.time() - t3
    timings["total"] = time.time() - t0
    res.files.update(write_provenance(res, cfg, opts))
    log(f"Done in {timings['total']:.0f}s")
    return res


def _write_dem(path: Path, grid: Grid, epsg: int) -> Path:
    """32-bit float TIFF + world file + .prj (GDAL, QGIS, ArcGIS, Civil 3D
    all georeference it from the sidecars)."""
    from PIL import Image
    from PIL import TiffImagePlugin

    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    c0 = grid.cell
    # GeoTIFF: pixel scale, tie point (upper-left), and geokeys. EPSG codes go
    # in ProjectedCSTypeGeoKey; Esri-only codes rely on the .prj sidecar.
    ifd[33550] = (c0, c0, 0.0)
    ifd.tagtype[33550] = 12
    ifd[33922] = (0.0, 0.0, 0.0, grid.x0, grid.y1, 0.0)
    ifd.tagtype[33922] = 12
    keys = [1, 1, 0, 0, 1024, 0, 1, 1, 1025, 0, 1, 1]  # projected model, PixelIsArea
    if epsg < 32767:
        keys += [3072, 0, 1, epsg]
    keys[3] = (len(keys) - 4) // 4
    ifd[34735] = tuple(keys)
    ifd.tagtype[34735] = 3
    ifd[42113] = "-9999"  # GDAL_NODATA
    ifd.tagtype[42113] = 2
    Image.fromarray(np.nan_to_num(grid.z, nan=-9999.0).astype("float32"), mode="F").save(path, compression="tiff_deflate", tiffinfo=ifd)
    c = grid.cell
    path.with_suffix(".tfw").write_text(f"{c}\n0\n0\n{-c}\n{grid.x0 + c / 2}\n{grid.y1 - c / 2}\n")
    path.with_suffix(".prj").write_text(crs_mod.make_crs(epsg).to_wkt("WKT1_ESRI"))
    return path


def zoning_coverage(res: RunResult) -> str:
    """Coverage outcome for the anonymous usage record (no location below city or township):
    covered | no_zoning | no_district | none."""
    z = res.zoning
    if not z:
        return "none"
    if z.get("no_zoning"):
        return "no_zoning"
    return "covered" if z.get("zones") else "no_district"


def result_json(res: RunResult) -> str:
    return json.dumps({"flags": res.flags, "files": res.files, "timings": res.timings}, indent=2)
