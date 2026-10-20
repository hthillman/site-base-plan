"""Address -> (lon, lat, county, state). Tries several free geocoders in
order and keeps the first confident US hit (in the hinted state, if given)."""

from __future__ import annotations

import os
from dataclasses import dataclass

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


class GeocodeError(RuntimeError):
    pass


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
        return GeocodeHit(c["x"], c["y"], m["matchedAddress"], counties[0]["BASENAME"] if counties else None,
                          "US Census Geocoder (TIGER address ranges)", st)
    return None


def _esri(addr: str, want: str | None) -> GeocodeHit | None:
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
        if not _ok(a.get("RegionAbbr"), want) or c.get("score", 0) < 85:
            continue
        if a.get("Addr_type") not in ("PointAddress", "Subaddress", "StreetAddress", "StreetAddressExt", "Parcel"):
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
    for fn in GEOCODERS:
        try:
            hit = fn(addr, state)
            if hit:
                return hit, errors
            errors.append(f"{fn.__name__.strip('_')}: no confident US match" + (f" in {state}" if state else ""))
        except Exception as e:  # noqa: BLE001 - try the next one
            errors.append(f"{fn.__name__.strip('_')}: {e}")
    raise GeocodeError("Could not geocode the address. " + "; ".join(errors))
