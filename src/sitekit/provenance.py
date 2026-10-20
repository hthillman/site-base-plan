"""provenance.json (machine) + provenance.md (human) for every run."""

from __future__ import annotations

import json
import shutil

from .config import DISCLAIMER
from .crs import wkid_text
from .model import now_iso


def write_provenance(res, cfg, opts) -> dict[str, str]:
    site = res.site
    out = res.out_dir
    shutil.copy(cfg.source_file, out / "layers.toml")
    data = {
        "generated_at": now_iso(),
        "tool": "Basesheet (https://basesheet.site, source: https://github.com/hthillman/site-base-plan)",
        "disclaimer": DISCLAIMER,
        "input": {"query": site.query, "buffer_ft": site.buffer_ft, "contour_interval_ft": opts.contour_interval},
        "site": {
            "matched_address": site.matched_address, "geocoder": site.geocoder,
            **({} if site.geocoder.startswith("Esri") else {"lon": site.lon, "lat": site.lat}), "county": site.county,
            "parcel_source": site.parcel_source, "parcel_ids": site.parcel_ids,
            "parcel_attributes": {k: v for k, v in (site.parcel.props if site.parcel else {}).items() if k not in ("Shape__Area", "Shape__Length", "GlobalID")},
            "state": site.state,
            "crs": {"wkid": site.epsg, "label": site.crs_label, "units": site.units, "vertical_datum": f"NAVD88 ({site.units})"},
            "extent": dict(zip(("xmin", "ymin", "xmax", "ymax"), site.clip.bounds)),
            "warnings": site.warnings,
        },
        "layers": [lr.summary() for lr in res.layers.values()],
        "lidar_sources": res.layers["dem"].extra.get("lidar", []),
        "dxf_layers": {st.key: {"name": st.name, "description": st.description} for st in cfg.layers.values()},
        "slope_band_layers": [{"lo": lo, "hi": hi, "layer": name} for lo, hi, name, _ in cfg.slope_bands()],
        "contour_entity": cfg.contour_entity,
        "dwg_converter": __import__("sitekit.export_dxf", fromlist=["dwg_converter"]).dwg_converter() if any(k.startswith("dwg") for k in res.files) else None,
        "base_point": dict(zip(("e", "n"), __import__("sitekit.export_dxf", fromlist=["base_point"]).base_point(site.clip))),
        "flags": res.flags,
        "testfit": __import__("sitekit.testfit.export", fromlist=["provenance"]).provenance(getattr(res, "testfit", None))
        if __import__("sitekit.plugins", fromlist=["testfit_available"]).testfit_available() else {},
        "files": {k: str(v) for k, v in res.files.items()},
        "timings_s": {k: round(v, 1) for k, v in res.timings.items()},
    }
    jp = out / "provenance.json"
    jp.write_text(json.dumps(data, indent=2, default=str))

    md = [f"# Data provenance: {site.matched_address}", "", f"> {DISCLAIMER}", ""]
    md += [
        f"- Generated: {data['generated_at']}",
        f"- Input: `{site.query}` (buffer {site.buffer_ft:g} ft, contours {opts.contour_interval:g} ft)",
        f"- Geocoder: {site.geocoder}" + ("" if site.geocoder.startswith("Esri") else f"; lon/lat {site.lon:.6f}, {site.lat:.6f}") ,
        f"- County: {site.county}; parcel IDs: {', '.join(site.parcel_ids) or 'not resolved'}",
        f"- Parcel source: {site.parcel_source or 'NOT RESOLVED'}",
        f"- Coordinate system: {site.crs_label} ({wkid_text(site.epsg)}); elevations {site.units} NAVD88",
        "",
        "## Flags",
        "",
    ]
    md += [f"- **{f['level'].upper()}**: {f['text']}" for f in res.flags]
    md += ["", "## Layers", ""]
    for lr in res.layers.values():
        md += [f"### {lr.title} — {lr.status.upper()}", "", f"- Source: {lr.source}"]
        if lr.url:
            md.append(f"- Endpoint: {lr.url}")
        md += [
            f"- Retrieved: {lr.retrieved_at or 'n/a'}",
            f"- Resolution: {lr.resolution or 'n/a'}",
            f"- Vintage: {lr.vintage or 'not reported by source'}",
            f"- Features in extent: {len(lr.features)}",
        ]
        if lr.error:
            md.append(f"- **Error:** {lr.error}")
        for n in lr.notes:
            md.append(f"- Note: {n}")
        if lr.limitations:
            md.append("- Known limitations:")
            md += [f"  - {x}" for x in lr.limitations]
        md.append("")
    tfp = data.get("testfit") or {}
    if tfp:
        md += ["## Test fit (walk-up apartments)", "", f"- Status: {tfp['status']}" + (f" ({tfp['message']})" if tfp.get("message") else "")]
        for z in tfp.get("zones", []):
            md.append(f"- Zone: {z['jurisdiction']} {z['zone']} {z['name']} ({z['share']:.0%} of parcel)")
        if tfp.get("rules"):
            r = tfp["rules"]
            md.append(f"- Rules: {r['status'].upper()} sheet from {r['code_title']} ({r['code_url']}), read {r['code_retrieved']}. Draft sheets are AI-extracted and unreviewed.")
        for i, o in enumerate(tfp.get("options", []), 1):
            md.append(f"- Option {i}: {o['units']} units, limited by {o['limiting']}; {o['stalls']}/{o['stalls_required']} stalls; {o['orientation']}")
            md += [f"  - {'OK' if c['ok'] else ('n/a' if c['ok'] is None else 'FAILS')} {c['rule']}: limit {c['limit']}, drawn {c['actual']} ({c.get('cite', '')})" for c in o["checks"]]
        md.append("")
    lidar = res.layers["dem"].extra.get("lidar") or []
    if lidar:
        md += ["## LiDAR projects under the extent (3DEP index)", "", "| Project | Collected | Quality | Source GSD (m) | Coverage |", "|---|---|---|---|---|"]
        md += [f"| {s['project']} | {s['collect_start']} – {s['collect_end']} | {s['quality_level']} | {s['dem_gsd_m']} | {(f"{s['coverage']:.0%}" if s['coverage'] is not None else 'n/a')} |" for s in lidar]
        md.append("")
    md += ["## DXF layers", "", "| Key | Layer | Contents |", "|---|---|---|"]
    md += [f"| {st.key} | `{st.name}` | {st.description} |" for st in cfg.layers.values()]
    md += [f"| slope band | `{name}` | Slope {lo:g}–{hi:g}% |" if hi is not None else f"| slope band | `{name}` | Slope {lo:g}%+ |" for lo, hi, name, _ in cfg.slope_bands()]
    bx, by = data["base_point"]["e"], data["base_point"]["n"]
    md += ["", "## Two DXFs, one drawing", "",
           f"- `site.dxf`: true State Plane coordinates ({wkid_text(site.epsg)}, {site.units}). Use in AutoCAD / Civil 3D alongside other State Plane data.",
           f"- `site-local.dxf`: identical, moved by (-{bx:,.0f}, -{by:,.0f}) so base point E {bx:,.0f} N {by:,.0f} sits at 0,0. Use in SketchUp, which loses precision far from the origin.",
           "- Both carry the base point on layer SITE-BASEPOINT."]
    if data["dwg_converter"]:
        md += [f"- DWG files converted with {data['dwg_converter']}."]
        if "LibreDWG" in data["dwg_converter"]:
            md += ["  LibreDWG's DWG writer is experimental. If AutoCAD reports errors, run RECOVER or open the DXF instead (AutoCAD opens DXF natively)."]
    md += ["", "## Files", ""] + [f"- {k}: `{v}`" for k, v in res.files.items()]
    mp = out / "provenance.md"
    mp.write_text("\n".join(md) + "\n")
    return {"provenance_json": str(jp), "provenance_md": str(mp)}
