# Statewide parcel sources

One file per state: `parcels/<ST>.toml` (two-letter postal code). Only free,
public services that need no API key or login, answer ArcGIS REST `query`
requests with polygon geometry, and were **verified with live queries**.

```toml
state = "FL"
name = "Florida Statewide Cadastral"
publisher = "Florida Geographic Information Office"
url = "https://.../FeatureServer/0"     # the polygon LAYER (ends in /<id>)
apn_fields = ["PARCEL_ID", "PARCELNO"]  # fields a user's parcel number could match, most likely first
situs_field = "PHY_ADDR1"               # street address field, "" if none
city_field = "PHY_CITY"                 # "" if none
county_field = "CO_NO"                  # "" if none
county_values = "fips"                  # fips | name | code (state-specific code) | none
coverage = "All 67 counties"            # or list the missing counties
vintage = "2025 tax roll (updated annually)"
max_record_count = 2000
terms = "Public; attribution: Florida Department of Revenue / FGIO"
notes = ""
# Optional attribute fields for labels (exact field names; omit if absent):
owner_field = "OWN_NAME"
deed_book_field = "OR_BOOK1"            # or deed_ref_field for a combined "book/page" field
deed_page_field = "OR_PAGE1"
plat_book_field = ""                    # or plat_ref_field for a combined reference
plat_page_field = ""
legal_field = "S_LEGAL"
subdivision_field = ""
county = ""                             # county-level sources only (parcels/counties/<ST>/<County>.toml)

[verified]
date = "2026-10-19"
point = [-81.3792, 28.5383]             # lon, lat used for the test
point_result = "PARCEL_ID 12345 at 1 Main St, Orlando"
apn_test = "PARCEL_ID = '12345' returned 1 polygon"
```

Rules:
- Verify by actually calling `<url>/query` with `geometry=<lon>,<lat>&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=json`, in a real city in that state, and again with a `where` on an apn field. Record what came back.
- Prefer the state GIS office / official state portal. A county-by-county compilation is fine if it is one service.
- Skip a state rather than guess. Do not include services that need tokens, are owned by private individuals, or look like one-off student/consultant copies.
- Validate each file: `python3 -c "import tomllib,sys;tomllib.load(open(sys.argv[1],'rb'))" <file>`.
