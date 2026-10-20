"""Resolve a geocoded point or a parcel number (APN) to a parcel polygon.

Sources are per state: data/parcels/<ST>.toml (format in SCHEMA.md), each a
free statewide service verified with live queries. States without one still
work: the pipeline falls back to an assumed extent around the point and
flags it loudly.

Every returned Feature carries normalised props alongside the raw ones:
  _APN, _SITUS, _CITY, _COUNTY (county name or code as the source has it)
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point

from .http import get_json
from .model import Feature
from .sources.arcgis import query_features

SOURCES_DIR = Path(__file__).resolve().parent / "data" / "parcels"

WA_FIPS = {
    "001": "Adams", "003": "Asotin", "005": "Benton", "007": "Chelan", "009": "Clallam",
    "011": "Clark", "013": "Columbia", "015": "Cowlitz", "017": "Douglas", "019": "Ferry",
    "021": "Franklin", "023": "Garfield", "025": "Grant", "027": "Grays Harbor", "029": "Island",
    "031": "Jefferson", "033": "King", "035": "Kitsap", "037": "Kittitas", "039": "Klickitat",
    "041": "Lewis", "043": "Lincoln", "045": "Mason", "047": "Okanogan", "049": "Pacific",
    "051": "Pend Oreille", "053": "Pierce", "055": "San Juan", "057": "Skagit", "059": "Skamania",
    "061": "Snohomish", "063": "Spokane", "065": "Stevens", "067": "Thurston", "069": "Wahkiakum",
    "071": "Walla Walla", "073": "Whatcom", "075": "Whitman", "077": "Yakima",
}

# County assessor services tried after a state's statewide layer misses.
COUNTY_FALLBACKS = {
    "WA": {"King": {"url": "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_Parcels/MapServer/0", "apn_field": "PIN"}},
}


@dataclass
class ParcelSource:
    state: str
    name: str
    publisher: str
    url: str
    apn_fields: list[str]
    situs_field: str = ""
    city_field: str = ""
    county_field: str = ""
    county_values: str = "none"
    coverage: str = ""
    vintage: str = ""
    terms: str = ""
    notes: str = ""
    verified: dict = field(default_factory=dict)
    county: str = ""
    owner_field: str = ""
    deed_book_field: str = ""
    deed_page_field: str = ""
    deed_ref_field: str = ""
    plat_book_field: str = ""
    plat_page_field: str = ""
    plat_ref_field: str = ""
    legal_field: str = ""
    subdivision_field: str = ""

    def covers_county(self, county: str | None) -> bool | None:
        """True/False when the coverage note lists missing (or included)
        counties; None when coverage can't be judged by county."""
        if not county or not self.coverage:
            return None
        key = _county_key(county)
        cov = self.coverage
        m = re.search(r"Missing:\s*([^(\n]+)", cov)
        if m:
            missing = {_county_key(x) for x in re.split(r",|\band\b", m.group(1)) if x.strip()}
            return key not in missing
        m = re.search(r"only:\s*([^.\n]+)", cov)
        if m:
            included = [x.strip().lower() for x in m.group(1).split(",")]
            return any(key and key in x for x in included)
        return None

    def unpublished(self) -> list[str]:
        """Record fields this source doesn't publish at all."""
        out = []
        if not self.owner_field:
            out.append("owner names")
        if not (self.deed_book_field or self.deed_ref_field):
            out.append("deed references")
        if not (self.plat_book_field or self.plat_ref_field):
            out.append("plat references")
        return out

    @property
    def partial(self) -> bool:
        c = (self.coverage or "").lower()
        return bool(c) and not c.startswith(("all ", "statewide", "whole", "entire"))

    @property
    def label(self) -> str:
        return f"{self.name} ({self.publisher})" if self.publisher and self.publisher not in self.name else self.name


@lru_cache(maxsize=1)
def all_sources() -> dict[str, ParcelSource]:
    out = {}
    for p in sorted(SOURCES_DIR.glob("*.toml")):
        d = tomllib.loads(p.read_text())
        keys = ParcelSource.__dataclass_fields__.keys()
        out[d["state"]] = ParcelSource(**{k: v for k, v in d.items() if k in keys})
    return out


@lru_cache(maxsize=1)
def county_sources() -> dict[str, dict[str, ParcelSource]]:
    """{state: {county_name_lower: source}} from data/parcels/counties/<ST>/*.toml."""
    out: dict[str, dict[str, ParcelSource]] = {}
    keys = ParcelSource.__dataclass_fields__.keys()
    for p in sorted((SOURCES_DIR / "counties").glob("*/*.toml")):
        d = tomllib.loads(p.read_text())
        src = ParcelSource(**{k: v for k, v in d.items() if k in keys})
        src.state = src.state or p.parent.name
        src.county = src.county or p.stem
        out.setdefault(src.state.upper(), {})[_county_key(src.county)] = src
    return out


def _county_key(name: str | None) -> str:
    return re.sub(r"\s+(county|parish|borough)$", "", (name or "").strip().lower())


def source_for(state: str | None, county: str | None = None) -> ParcelSource | None:
    """Statewide layer if the state has one, otherwise that county's layer."""
    st = (state or "").upper()
    if st in all_sources():
        return all_sources()[st]
    if county:
        return county_sources().get(st, {}).get(_county_key(county))
    return None


def county_coverage(state: str | None) -> list[str]:
    return sorted(s.county for s in county_sources().get((state or "").upper(), {}).values())


def supported_states() -> list[str]:
    return sorted(all_sources())


@lru_cache(maxsize=64)
def _field_types(url: str) -> dict[str, str]:
    try:
        info = get_json(url, {"f": "json"}, timeout=30)
        return {f["name"]: f.get("type", "") for f in info.get("fields", [])}
    except Exception:  # noqa: BLE001
        return {}


def _normalise(f: Feature, src: ParcelSource) -> Feature:
    p = f.props
    apn = next((str(p[k]).strip() for k in src.apn_fields if p.get(k) not in (None, "", " ")), "")
    p["_APN"] = apn
    p["_SITUS"] = str(p.get(src.situs_field) or "").strip() if src.situs_field else ""
    p["_CITY"] = str(p.get(src.city_field) or "").strip() if src.city_field else ""
    raw_county = p.get(src.county_field) if src.county_field else None
    p["_COUNTY"] = county_name(raw_county, src.state) if src.county_values == "fips" and src.state == "WA" else (
        str(raw_county).strip() if raw_county not in (None, "") and src.county_values == "name" else "")
    if src.county and not p["_COUNTY"]:
        p["_COUNTY"] = src.county

    def val(fld):
        v = p.get(fld) if fld else None
        if v in (None, "", " ", 0, "0"):
            return ""
        t = str(int(v)) if isinstance(v, float) and v.is_integer() else " ".join(str(v).split())
        return "" if not t.strip("0 ./-") else t  # all-zero placeholders mean "none"

    p["_OWNER"] = val(src.owner_field)
    def ref(book_f, page_f, ref_f, b, pg):
        # Some publishers keep book and page in one combined field.
        if book_f and book_f == page_f:
            return val(book_f)
        bk, pp = val(book_f), val(page_f)
        return f"{b} {bk} {pg} {pp}" if bk and pp else (f"{b} {bk}" if bk else val(ref_f))

    p["_DEED"] = ref(src.deed_book_field, src.deed_page_field, src.deed_ref_field, "DB", "PG")
    p["_PLAT"] = ref(src.plat_book_field, src.plat_page_field, src.plat_ref_field, "PB", "PG")
    if p["_DEED"] and not p["_DEED"].upper().startswith(("DB", "BK", "BOOK")) and src.deed_book_field == src.deed_page_field:
        p["_DEED"] = f"DB/PG {p['_DEED']}"
    if p["_PLAT"] and not p["_PLAT"].upper().startswith(("PB", "PL", "PLAT")) and src.plat_book_field and src.plat_book_field == src.plat_page_field:
        p["_PLAT"] = f"PB/PG {p['_PLAT']}"
    p["_LEGAL"] = val(src.legal_field)[:200]
    p["_SUBDIV"] = val(src.subdivision_field)
    return f


def county_name(code_or_name, state: str = "WA") -> str | None:
    if code_or_name in (None, ""):
        return None
    s = str(code_or_name).strip()
    if s.isdigit() and state == "WA":
        return WA_FIPS.get(s.zfill(3)[-3:])
    if s.isdigit():
        return None
    return re.sub(r"\s+(County|Parish|Borough)$", "", s, flags=re.I).title()


def county_at(lon: float, lat: float) -> str | None:
    """County name at a point, from the Census reverse geocoder."""
    try:
        d = get_json("https://geocoding.geo.census.gov/geocoder/geographies/coordinates",
                     {"x": lon, "y": lat, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "layers": "Counties", "format": "json"}, timeout=30)
        c = d.get("result", {}).get("geographies", {}).get("Counties", [])
        return c[0]["BASENAME"] if c else None
    except Exception:  # noqa: BLE001
        return None


def looks_like_apn(q: str) -> bool:
    """Parcel numbers are digits with dashes/dots/spaces and maybe a few
    letters (e.g. 'R12345', '123-45-678A'); addresses have street words."""
    s = q.strip()
    if "," in s or len(s) < 5 or len(s) > 30:
        return False
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z\-\. ]+", s):
        return False
    digits = sum(ch.isdigit() for ch in s)
    letters = sum(ch.isalpha() for ch in s)
    return digits >= 5 and letters <= 3 and not re.search(r"[A-Za-z]{3,}", s)


def _pick(feats: list[Feature], pt: Point | None) -> tuple[Feature | None, list[str]]:
    if not feats:
        return None, []
    ids = sorted({f.props.get("_APN", "") for f in feats} - {""})
    pool = [f for f in feats if pt is not None and f.geom.contains(pt)] or feats
    return max(pool, key=lambda f: f.geom.area), ids  # stacked condos share a footprint


def parcel_at_point(lon: float, lat: float, out_sr: int, state: str | None = None, county: str | None = None) -> tuple[Feature | None, str, list[str], list[str]]:
    """Returns (parcel, source label, all ids at point, errors)."""
    from .crs import reproject

    errors: list[str] = []
    src = source_for(state, county)
    pt_ll = Point(lon, lat)
    pt = reproject(pt_ll, 4326, out_sr)
    if src is None:
        errors.append(f"No parcel source for {county + ' County, ' if county else ''}{state or 'this state'} yet.")
    else:
        try:
            feats = [_normalise(f, src) for f in query_features(src.url, geometry=pt_ll, in_sr=4326, out_sr=out_sr)]
            best, ids = _pick(feats, pt)
            if best:
                return best, src.label, ids, errors
            errors.append(f"{src.name}: no parcel at point (coverage: {src.coverage or 'n/a'})")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src.name}: {e}")
    for county, cfg in COUNTY_FALLBACKS.get((state or "").upper(), {}).items():
        try:
            feats = query_features(cfg["url"], geometry=pt_ll, in_sr=4326, out_sr=out_sr)
            for f in feats:
                f.props.update(_APN=str(f.props.get(cfg["apn_field"]) or ""), _SITUS="", _CITY="", _COUNTY=county)
            best, ids = _pick(feats, pt)
            if best:
                return best, f"{county} County assessor GIS", ids, errors
        except Exception as e:  # noqa: BLE001
            errors.append(f"{county} County parcels: {e}")
    return None, "", [], errors


def _apn_where(src: ParcelSource, apn: str) -> str:
    raw = apn.strip()
    cands = {raw, re.sub(r"[^0-9A-Za-z]", "", raw), raw.upper()}
    types = _field_types(src.url)
    parts = []
    for fld in src.apn_fields:
        t = types.get(fld, "esriFieldTypeString")
        if t in ("esriFieldTypeString", ""):
            quoted = ",".join("'" + c.replace("'", "''") + "'" for c in sorted(cands) if c)
            parts.append(f"{fld} IN ({quoted})")
        else:
            nums = sorted({c for c in cands if c.isdigit()})
            if nums:
                parts.append(f"{fld} IN ({','.join(nums)})")
    return " OR ".join(parts) or "1=0"


def parcel_by_apn(apn: str, out_sr: int, state: str, county: str | None = None) -> tuple[list[Feature], str, list[str]]:
    errors: list[str] = []
    src = source_for(state, county)
    if src is None:
        if county_coverage(state) and not county:
            return [], "", [f"{state} parcel lines come from county layers; pick the county for a parcel-number lookup."]
        return [], "", [f"Parcel-number lookup needs a parcel layer; none for {county + ' County, ' if county else ''}{state} yet. Use the street address."]
    where = _apn_where(src, apn)
    try:
        feats = [_normalise(f, src) for f in query_features(src.url, where=where, out_sr=out_sr)]
        if county and feats:
            c = county.lower().replace(" county", "")
            narrowed = [f for f in feats if not f.props.get("_COUNTY") or f.props["_COUNTY"].lower() == c]
            feats = narrowed or feats
        if feats:
            return feats, src.label, errors
        errors.append(f"{src.name}: parcel number not found")
    except Exception as e:  # noqa: BLE001
        errors.append(f"{src.name}: {e}")
    digits = re.sub(r"[^0-9]", "", apn)
    for cname, cfg in COUNTY_FALLBACKS.get(state.upper(), {}).items():
        if county and county.lower() != cname.lower():
            continue
        try:
            feats = query_features(cfg["url"], where=f"{cfg['apn_field']} = '{digits}'", out_sr=out_sr)
            for f in feats:
                f.props.update(_APN=digits, _SITUS="", _CITY="", _COUNTY=cname)
            if feats:
                return feats, f"{cname} County assessor GIS", errors
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cname} County parcels: {e}")
    return [], "", errors


def parcel_by_situs(addr: str, out_sr: int, state: str | None, county: str | None = None) -> list[Feature]:
    """Last-resort lookup by the assessor situs address string."""
    src = source_for(state, county)
    if src is None or not src.situs_field:
        return []
    m = re.match(r"\s*(\d+)\s+([^,]+)", addr)
    if not m:
        return []
    number, street = m.group(1), m.group(2).upper()
    words = [w for w in re.split(r"\s+", street) if w not in ("N", "S", "E", "W", "NE", "NW", "SE", "SW")]
    if not words:
        return []
    first = words[0].replace("'", "''")
    where = f"UPPER({src.situs_field}) LIKE '{number} %{first}%'"
    try:
        return [_normalise(f, src) for f in query_features(src.url, where=where, out_sr=out_sr)][:5]
    except Exception:  # noqa: BLE001
        return []


# Back-compat for the Thurston test fit (neighbouring-parcel lookup).
STATEWIDE_URL = "https://services.arcgis.com/jsIt88o09Q0r1j8h/arcgis/rest/services/Current_Parcels/FeatureServer/0"
