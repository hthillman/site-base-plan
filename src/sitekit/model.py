"""Shared result types. Every data layer reports what happened to it, so the
PDF and provenance log can show missing or failed layers instead of quietly
leaving them out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shapely.geometry.base import BaseGeometry


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Feature:
    geom: BaseGeometry
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerResult:
    key: str
    title: str
    source: str
    url: str
    status: str = "pending"  # ok | empty | failed | skipped
    retrieved_at: str = ""
    resolution: str = ""
    vintage: str = ""
    limitations: list[str] = field(default_factory=list)
    error: str = ""
    notes: list[str] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def ok(self) -> bool:
        return self.status == "ok"

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "source": self.source,
            "url": self.url,
            "retrieved_at": self.retrieved_at,
            "resolution": self.resolution,
            "vintage": self.vintage,
            "limitations": self.limitations,
            "notes": self.notes,
            "error": self.error,
            "feature_count": len(self.features),
        }


@dataclass
class Site:
    query: str
    matched_address: str
    lon: float
    lat: float
    county: str
    epsg: int
    crs_label: str
    parcel: Feature | None
    parcel_source: str
    parcel_ids: list[str]
    clip: BaseGeometry  # rectangle in State Plane ft
    buffer_ft: float
    geocoder: str
    warnings: list[str] = field(default_factory=list)
    parcels: list = field(default_factory=list)  # individual parcels when several are combined
    state: str = "WA"
    units: str = "US survey ft"          # horizontal + vertical foot of the CRS
    ft_per_m: float = 3937 / 1200
