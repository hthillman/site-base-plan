# Building footprint sources

Accurate building outlines published by counties, cities or states (planimetric
or LiDAR-derived), used instead of the nationwide machine-traced USA Structures
layer wherever one covers the site.

Files:
- `buildings/<ST>.toml` for a statewide layer (only if it's genuinely planimetric, not another ML trace).
- `buildings/counties/<ST>/<County>.toml` for a county or consolidated city-county layer. `county` is the plain county name as the
  Census geocoder returns it ("Los Angeles", "St. Louis City"). A city layer that covers only part of a county is allowed if the
  city is most of the county (e.g. Philadelphia); say so in `coverage`.

```toml
state = "TX"
county = "Harris"
name = "City of Houston Building Footprints"
publisher = "City of Houston GIS (COHGIS)"
url = "https://.../FeatureServer/0"      # the polygon LAYER (ends in /<id>)
coverage = "City of Houston only (about 60% of Harris County)"
method = "planimetric"                   # planimetric | lidar | imagery-traced (say which the publisher states)
vintage = "Flown 2022, updated 2024"
terms = "Public; City of Houston open data"
max_record_count = 2000
# Heights, if the layer has them (exact field names; leave out if absent):
height_field = "HEIGHT"                  # building height
height_units = "ft"                      # ft | m
top_elev_field = ""                      # or roof and ground elevations, height = top - base
base_elev_field = ""
stories_field = ""                       # number of floors, used only if there is no height
notes = ""
filter = ""                              # SQL for layers shared by several counties

[verified]
date = "2026-10-21"
point = [-95.3698, 29.7604]              # lon, lat used for the test (a dense block is best)
point_result = "38 footprints within 150 m; HEIGHT present on 36"
```

Rules (same spirit as the parcel registry):
- ArcGIS REST FeatureServer/MapServer polygon layers only, answering `/query` with geometry, no token or login, published by the
  county, city, state or their official open data portal.
- Must be real outlines (planimetric capture or LiDAR-derived). Skip layers that are just a copy of Microsoft or USA Structures
  footprints (check the item description / source field).
- Verify live: an envelope query around a dense block with `inSR=4326` and `outSR` = a State Plane EPSG for the state, confirm
  polygons come back in feet near the point, and note how many have a height.
- Terms: record faithfully. Skip vendor-licensed data, no-redistribution clauses, agreements or indemnity clauses.
- Validate: `python3 -c "import tomllib,sys;tomllib.load(open(sys.argv[1],'rb'))" <file>`, then
  `uv run python scripts/check_buildings.py <ST>` from the repo root.
