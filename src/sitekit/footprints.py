"""Registry of accurate building-footprint layers (county, city or statewide),
used in place of the nationwide machine-traced USA Structures layer where one
covers the site. Format in data/buildings/SCHEMA.md."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "data" / "buildings"


@dataclass
class BuildingSource:
    state: str
    name: str
    publisher: str
    url: str
    county: str = ""
    coverage: str = ""
    method: str = ""
    vintage: str = ""
    terms: str = ""
    max_record_count: int = 1000
    height_field: str = ""
    height_units: str = "ft"
    top_elev_field: str = ""
    base_elev_field: str = ""
    stories_field: str = ""
    notes: str = ""
    filter: str = ""
    verified: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.publisher})" if self.publisher and self.publisher not in self.name else self.name

    def out_fields(self) -> str:
        f = [x for x in (self.height_field, self.top_elev_field, self.base_elev_field, self.stories_field) if x]
        return ",".join(f) or "*"  # some layers name their id field differently, so don't guess one

    def height_ft(self, props: dict, ft_per_m: float) -> float | None:
        """Building height in the site's feet, or None if this record has none."""
        def num(k):
            v = props.get(k) if k else None
            return float(v) if isinstance(v, (int, float)) else None

        h = num(self.height_field)
        if h is None and self.top_elev_field and self.base_elev_field:
            top, base = num(self.top_elev_field), num(self.base_elev_field)
            h = top - base if top is not None and base is not None else None
        if h is not None:
            h = h * ft_per_m if self.height_units == "m" else h
        elif num(self.stories_field):
            h = num(self.stories_field) * 11.0  # rough floor-to-floor; flagged as an estimate
        return h if h is not None and 6 <= h <= 1500 else None


def _load(p: Path) -> BuildingSource:
    d = tomllib.loads(p.read_text())
    keys = BuildingSource.__dataclass_fields__.keys()
    return BuildingSource(**{k: v for k, v in d.items() if k in keys})


@lru_cache(maxsize=1)
def statewide() -> dict[str, BuildingSource]:
    return {s.state.upper(): s for s in (_load(p) for p in sorted(DIR.glob("*.toml")))}


@lru_cache(maxsize=1)
def by_county() -> dict[str, dict[str, BuildingSource]]:
    from .parcel import _county_key

    out: dict[str, dict[str, BuildingSource]] = {}
    for p in sorted((DIR / "counties").glob("*/*.toml")):
        s = _load(p)
        s.state = (s.state or p.parent.name).upper()
        s.county = s.county or p.stem
        out.setdefault(s.state, {})[_county_key(s.county)] = s
    return out


def source_for(state: str | None, county: str | None) -> BuildingSource | None:
    """County layer first (usually the most detailed), then a statewide one."""
    from .parcel import _county_key

    st = (state or "").upper()
    if county:
        s = by_county().get(st, {}).get(_county_key(county))
        if s:
            return s
    return statewide().get(st)


def all_sources() -> list[tuple[str, BuildingSource]]:
    out = [(st, s) for st, s in statewide().items()]
    out += [(st, s) for st, cs in by_county().items() for s in cs.values()]
    return out


def sources_for(state: str | None, county: str | None) -> list[BuildingSource]:
    """Every registry layer that might cover the site, most local first (county, then statewide)."""
    from .parcel import _county_key

    st = (state or "").upper()
    out = []
    if county and (c := by_county().get(st, {}).get(_county_key(county))):
        out.append(c)
    if st in statewide():
        out.append(statewide()[st])
    return out
