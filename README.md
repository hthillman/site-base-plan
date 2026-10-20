# Site Base Plan

Planning-level site base plans from any US address, built entirely from public data.
Type an address (or parcel number) and get a CAD-ready base plan in about a minute.

**Use it:** https://site-toolkit.vercel.app (free, no account)

Built for landscape architects, civil engineers, architects and anyone doing early site work.

## What you get

- **Base plan in State Plane feet** (US survey or international feet, per state): parcel line, neighbouring parcels with ID / owner / deed and plat references where published, road centerlines with names, approximate right-of-way, LiDAR contours, slope bands, soils, FEMA flood zones, NWI wetlands and an aerial underlay.
- **Files:** DXF (true coordinates, plus a copy moved near 0,0 for SketchUp), textured 3D terrain (COLLADA for SketchUp, OBJ), LandXML surface for Civil 3D, GeoJSON layers and a GeoTIFF DEM for GIS, KML for Google Earth, and a PDF summary with scaled sheets and plain-language findings.
- **Provenance:** every output lists each layer's source, date, resolution and known limits. A layer that fails to load is flagged as missing, never silently dropped.
- **Multi-parcel sites** (up to 5 parcels) and **CAD layer naming** (default, NCS-style, or your own mapping).

> **Planning-level data only.** Not a substitute for a survey by a licensed land surveyor. Parcel lines are assessor tax lines, not legal boundaries.

## Data sources

| Layer | Source |
|---|---|
| Parcels | Free statewide parcel layers (30 states) and county layers (GA so far): see `src/sitekit/data/parcels/` |
| Topography | USGS 3D Elevation Program (3DEP) |
| Soils | USDA NRCS SSURGO |
| Flood | FEMA National Flood Hazard Layer |
| Wetlands | USFWS National Wetlands Inventory |
| Roads | U.S. Census TIGER/Line |
| Imagery | Esri World Imagery (USDA NAIP fallback) |
| Coordinates | NGS State Plane zones (bundled) |

## Run it locally

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run sitekit "123 Main St, Springfield, IL"
uv run sitekit 0123456789 --state FL --also 0123456790 --layer-preset ncs
uv run sitekit-web        # local web UI at http://127.0.0.1:5055
```

Optional environment variables:

| Variable | Purpose |
|---|---|
| `ESRI_API_KEY` | ArcGIS Location Platform key for licensed geocoding and imagery (otherwise public endpoints are used) |
| `ESRI_REFERER` | Referrer sent with keyed Esri requests, if your key is referrer-restricted |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob store for hosted downloads (local runs write to `out/`) |
| `TIP_URL` | Optional donation link shown after a run |

## Add your county or state

Parcel coverage is the biggest gap, and the easiest thing to contribute. See [CONTRIBUTING.md](CONTRIBUTING.md): it's one small TOML file plus a live check.

## License

MIT. Data comes from the public sources above, each under its own terms (listed per parcel source and on the site's Data sources page).
