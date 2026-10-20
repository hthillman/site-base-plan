# Contributing

Thanks for helping. The most valuable contribution is **parcel coverage**: 20 states have no free statewide parcel layer, so many places need county layers.

## Add a county (or state) parcel source

1. **Find the service.** Your county's GIS / open-data portal usually has an ArcGIS REST "parcels" layer (a URL ending in `/FeatureServer/0` or `/MapServer/N`). It must be public: no login or token.
2. **Check it answers.** Open `<url>?f=json` to see the field names, then query a real address point:
   ```
   <url>/query?geometry=<lon>,<lat>&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&f=json
   ```
   and a parcel number: `<url>/query?where=<APN_FIELD>='<number>'&outFields=*&f=json`.
3. **Write the file.** Statewide: `src/sitekit/data/parcels/<ST>.toml`. County: `src/sitekit/data/parcels/counties/<ST>/<County>.toml`. The format, with every key explained, is in [`src/sitekit/data/parcels/SCHEMA.md`](src/sitekit/data/parcels/SCHEMA.md). Fill in `[verified]` with what your two test queries returned.
4. **Test it:**
   ```bash
   uv run sitekit "<an address in that county>"
   ```
   The site line should name your source and the findings should show the parcel area.
5. Open a pull request with the county, the publisher and what you tested.

Rules that keep the tool trustworthy:
- Prefer official county / state publishers. No copies hosted by individuals or consultants.
- Record coverage honestly (list missing towns or counties) and the data's vintage.
- If the publisher restricts commercial use, put that in `terms`.

## Other contributions

- **CAD layer presets** (`PRESETS` in `src/sitekit/config.py`) for common office standards.
- **Bug reports** with the address (or a nearby one) and what looked wrong.
- **Data fixes**: a source that moved, a field that changed name.

Please keep pull requests focused and explain how you checked the result.
