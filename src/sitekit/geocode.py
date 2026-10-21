"""Address -> (lon, lat, county, state). Tries several free geocoders in
order and keeps the first confident US hit (in the hinted state, if given)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .http import esri_headers, get_json

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_CODE = {v.lower(): k for k, v in STATES.items()}


@dataclass
class GeocodeHit:
    lon: float
    lat: float
    matched: str
    county: str | None
    source: str
    state: str
    score: float | None = None


def census_county(c: dict | None) -> str | None:
    """County name from a Census Counties record. NAME, not BASENAME, so independent cities stay distinct
    ('St. Louis city' vs St. Louis County, both BASENAME 'St. Louis'); the County/Parish suffix is dropped."""
    if not c:
        return None
    return re.sub(r"\s+(County|Parish|Borough|Census Area|Municipality)$", "", c.get("NAME") or c.get("BASENAME") or "") or None


class GeocodeError(RuntimeError):
    def __init__(self, msg: str, suggestions: list[str] | None = None, hint: str = "", near: dict | None = None):
        super().__init__(msg)
        self.suggestions = suggestions or []
        self.hint = hint  # coarse failure kind for anonymous usage stats; never the address
        self.near = near  # {lon, lat, zoom}: where to open the map picker (the town or street the geocoder did recognise)


NEAR_ZOOM = {"PointAddress": 18, "Subaddress": 18, "StreetAddress": 18, "StreetAddressExt": 18, "StreetInt": 18, "StreetName": 17,
             "PostalExt": 16, "POI": 16, "Neighborhood": 15, "District": 14, "Locality": 13, "City": 13, "Postal": 13,
             "PostalLoc": 13, "Subregion": 10, "Region": 7}
UNIT_RE = re.compile(r"(?i)(?:,\s*|\s+)(?:apt|apartment|unit|suite|ste|bldg|building|lot|trlr|trailer|space|spc|fl|floor|rm|room|#)\.?\s*#?\s*[\w-]+(?=,|$)")


def clean_address(addr: str) -> str:
    """Common reasons a real address doesn't match: unit numbers, ', USA', ZIP+4, stray punctuation."""
    a = UNIT_RE.sub("", addr)
    a = re.sub(r"(?i),?\s*(usa|u\.s\.a\.|united states( of america)?)\s*$", "", a)
    a = re.sub(r"\b(\d{5})-\d{4}\b", r"\1", a)
    a = re.sub(r"\s*,\s*,+", ",", a)
    a = re.sub(r"[;|]+", ",", a)
    return re.sub(r"\s{2,}", " ", a).strip(" ,.")


ADDRESS_TYPES = ("PointAddress", "Subaddress", "StreetAddress", "StreetAddressExt", "Parcel", "StreetInt")
COORD_RE = re.compile(r"^\s*\(?\s*(-?\d{1,3}(?:\.\d+)?)\s*[°]?\s*[NS]?\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*[°]?\s*[EW]?\s*\)?\s*$", re.I)


def parse_coords(text: str) -> tuple[float, float] | None:
    """'47.0379, -122.9007' (lat, lon, as copied from a map) or lon, lat -> (lon, lat) inside the US, else None."""
    m = COORD_RE.match(text or "")
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if re.search(r"\d\s*[°]?\s*W", text, re.I) and b > 0:
        b = -b
    for lat, lon in ((a, b), (b, a)):
        if 17 <= lat <= 72 and -180 <= lon <= -64:
            return lon, lat
    return None


def _coords(lon: float, lat: float) -> GeocodeHit | None:
    d = get_json("https://geocoding.geo.census.gov/geocoder/geographies/coordinates",
                 {"x": lon, "y": lat, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
                  "layers": "States,Counties", "format": "json"}, timeout=30)
    g = d.get("result", {}).get("geographies", {})
    st = (g.get("States") or [{}])[0].get("STUSAB")
    if st not in STATES:
        return None
    county = census_county((g.get("Counties") or [None])[0])
    return GeocodeHit(lon, lat, f"{lat:.6f}, {lon:.6f}", county, "Coordinates entered (state and county from US Census)", st)


def _ok(state: str | None, want: str | None) -> bool:
    return bool(state) and state in STATES and (not want or state == want)


def _census(addr: str, want: str | None) -> GeocodeHit | None:
    d = get_json(
        "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
        {"address": addr, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "layers": "Counties", "format": "json"},
        timeout=30,
    )
    for m in d.get("result", {}).get("addressMatches", []):
        st = m.get("addressComponents", {}).get("state")
        if not _ok(st, want):
            continue
        counties = m.get("geographies", {}).get("Counties", [])
        c = m["coordinates"]
        return GeocodeHit(c["x"], c["y"], m["matchedAddress"], census_county(counties[0]) if counties else None,
                          "US Census Geocoder (TIGER address ranges)", st)
    return None


def _esri(addr: str, want: str | None, suggestions: list[str] | None = None, near: list | None = None) -> GeocodeHit | None:
    params = {"SingleLine": addr, "f": "json", "maxLocations": 5, "outFields": "Score,Addr_type,Subregion,RegionAbbr", "countryCode": "USA"}
    key = os.environ.get("ESRI_API_KEY")
    d = None
    if key:
        # Location Platform keys use the geocode-api host.
        try:
            d = get_json("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
                         {**params, "token": key}, timeout=30, headers=esri_headers())
        except Exception as e:  # noqa: BLE001 - bad/expired key: use the public service rather than fail
            print(f"WARN esri key geocode failed: {e}", flush=True)
    if d is None:
        d = get_json("https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates", params, timeout=30)
    for c in d.get("candidates", []):
        a = c.get("attributes", {})
        if not _ok(a.get("RegionAbbr"), want):
            continue
        if near is not None and not near and c.get("score", 0) >= 60 and c.get("location"):
            near.append({"lon": c["location"]["x"], "lat": c["location"]["y"], "zoom": NEAR_ZOOM.get(a.get("Addr_type"), 12)})
        if a.get("Addr_type") not in ADDRESS_TYPES:
            continue
        if c.get("score", 0) < 85:
            if suggestions is not None and c.get("score", 0) >= 70 and c.get("address") not in suggestions:
                suggestions.append(c["address"])
            continue
        county = (a.get("Subregion") or "").replace(" County", "").replace(" Parish", "") or None
        return GeocodeHit(c["location"]["x"], c["location"]["y"], c["address"], county,
                          f"Esri World Geocoder ({a.get('Addr_type')})", a["RegionAbbr"], c.get("score"))
    return None


def _nominatim(addr: str, want: str | None) -> GeocodeHit | None:
    d = get_json(
        "https://nominatim.openstreetmap.org/search",
        {"q": addr, "format": "jsonv2", "addressdetails": 1, "countrycodes": "us", "limit": 3},
        timeout=30,
    )
    for h in d or []:
        ad = h.get("address", {})
        st = (ad.get("ISO3166-2-lvl4") or "").replace("US-", "") or NAME_TO_CODE.get((ad.get("state") or "").lower())
        if not _ok(st, want) or "house_number" not in ad:
            continue
        county = (ad.get("county") or "").replace(" County", "") or None
        return GeocodeHit(float(h["lon"]), float(h["lat"]), h["display_name"], county, "OpenStreetMap Nominatim", st)
    return None


GEOCODERS = [_esri, _census, _nominatim]


def geocode(addr: str, state: str | None = None) -> tuple[GeocodeHit, list[str]]:
    errors: list[str] = []
    ll = parse_coords(addr)
    if ll:
        try:
            hit = _coords(*ll)
        except Exception as e:  # noqa: BLE001
            raise GeocodeError(f"Couldn't look up the state for those coordinates ({e}). Try again in a moment.", hint="coords") from e
        if hit and (not state or hit.state == state):
            return hit, errors
        raise GeocodeError("Those coordinates aren't inside a US state" + (f" ({STATES.get(state, state)})" if state else "")
                           + ". Use latitude, longitude, e.g. 47.0379, -122.9007.", hint="coords")
    suggestions: list[str] = []
    near: list = []
    tries = [addr]
    cleaned = clean_address(addr)
    if cleaned and cleaned.lower() != addr.strip().lower():
        tries.append(cleaned)  # unit numbers, ', USA', ZIP+4 and stray punctuation are common reasons for a miss
    for attempt in tries:
        for fn in GEOCODERS:
            try:
                hit = fn(attempt, state, suggestions, near) if fn is _esri else fn(attempt, state)
                if hit:
                    return hit, errors
                errors.append(f"{fn.__name__.strip('_')}: no confident US match" + (f" in {state}" if state else ""))
            except Exception as e:  # noqa: BLE001 - try the next one
                errors.append(f"{fn.__name__.strip('_')}: {e}")
    print("geocode miss: " + "; ".join(errors), flush=True)
    where = f" in {STATES.get(state, state)}" if state else ""
    pin = " Or pick the site on the map below."
    if not re.search(r"\d", addr):
        raise GeocodeError(f"That looks like a place name, not a street address{where}. Enter a street address (123 Main St, Town, ST) "
                           "or a parcel number." + pin, suggestions[:3], hint="no_number", near=near[0] if near else None)
    msg = f"Couldn't find that address{where}."
    msg += (" Did you mean one of these?" if suggestions else " Check the spelling and include the city and state.") + pin
    raise GeocodeError(msg, suggestions[:3], hint="suggested" if suggestions else "no_match", near=near[0] if near else None)
