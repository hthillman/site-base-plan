"""Layer config + constants shared across the pipeline."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAYERS_FILE = REPO_ROOT / "config" / "layers.toml"

US_FT_PER_M = 3937 / 1200  # US survey foot

# Stamped across every drawing (PDF sheets, preview, DXF) and shown on the result page.
WATERMARK_LINES = ("NOT A SURVEY", "NOT FOR PERMIT SUBMISSION")
PARCEL_NOTE = "Assessor parcel line, not a surveyed boundary"  # beside every parcel line, in every format

DISCLAIMER = (
    "PLANNING-LEVEL DATA ONLY. Compiled from public GIS sources of varying "
    "resolution and vintage. Not a substitute for a boundary or topographic "
    "survey by a land surveyor licensed in the site's state. Parcel lines are assessor "
    "tax lines, not legal boundaries. Zoning information is not a zoning determination. "
    "Provided as is, without warranty: verify everything with a licensed surveyor and "
    "the jurisdiction before relying on it."
)


@dataclass
class LayerStyle:
    key: str
    name: str
    color: int
    linetype: str
    description: str


@dataclass
class Config:
    layers: dict[str, LayerStyle]
    slope_breaks: list[float]
    slope_colors: list[int]
    major_every: int
    contour_entity: str
    source_file: Path

    def layer(self, key: str) -> LayerStyle:
        return self.layers[key]

    def slope_bands(self) -> list[tuple[float, float | None, str, int]]:
        """[(lo, hi, layer_name, aci), ...]; hi is None for the open top band."""
        base = self.layers["slope"].name
        out = []
        for i, lo in enumerate(self.slope_breaks):
            hi = self.slope_breaks[i + 1] if i + 1 < len(self.slope_breaks) else None
            label = f"{lo:g}-{hi:g}" if hi is not None else f"{lo:g}PLUS"
            out.append((lo, hi, f"{base}-{label}", self.slope_colors[i % len(self.slope_colors)]))
        return out


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_LAYERS_FILE
    raw = tomllib.loads(p.read_text())
    layers = {
        k: LayerStyle(k, v["name"], int(v.get("color", 7)), v.get("linetype", "CONTINUOUS"), v.get("description", ""))
        for k, v in raw["layers"].items()
    }
    entity = raw.get("contours", {}).get("entity", "lwpolyline")
    if entity not in ("lwpolyline", "polyline3d"):
        raise ValueError(f"contours.entity must be lwpolyline or polyline3d, got {entity!r}")
    return Config(
        layers=layers,
        slope_breaks=[float(b) for b in raw["slope"]["breaks"]],
        slope_colors=[int(c) for c in raw["slope"]["colors"]],
        major_every=int(raw.get("contours", {}).get("major_every", 5)),
        contour_entity=entity,
        source_file=p,
    )


# ---------------------------------------------------------------- layer naming
# "NCS-style" follows the U.S. National CAD Standard pattern
# (discipline - major - minor): V = survey/existing conditions, C = civil,
# G = general, A = architectural. It's a sensible starting point, not a
# certified NCS layer list; offices tweak it with a custom mapping.
PRESETS: dict[str, dict[str, str]] = {
    "default": {},
    "ncs": {
        "parcel": "V-PROP-LINE", "parcel_site": "V-PROP-SITE", "clip": "G-ANNO-LIMT",
        "contour_major": "V-TOPO-MAJR", "contour_minor": "V-TOPO-MINR", "contour_label": "V-TOPO-TEXT",
        "parcel_adj": "V-PROP-ADJC", "parcel_adj_label": "V-PROP-TEXT",
        "road_cl": "V-ROAD-CNTR", "road_label": "V-ROAD-TEXT", "row": "V-PROP-RWAY",
        "soils": "V-SOIL", "soils_label": "V-SOIL-TEXT", "flood": "C-FLOD", "flood_label": "C-FLOD-TEXT",
        "wetland": "V-WETL", "wetland_label": "V-WETL-TEXT", "slope": "C-TOPO-SLOP",
        "aerial": "G-IMAG", "basepoint": "V-CTRL-BASE", "notes": "G-ANNO-NOTE",
        "bldg": "V-BLDG-OTLN", "bldg_mass": "A-MASS-EXST", "envelope_mass": "A-MASS-ENVL",
        "tf_buildable": "C-STDY-ENVL", "tf_constraint": "C-STDY-CNST", "tf_bldg": "A-STDY-{n}-BLDG",
        "tf_parking": "C-STDY-{n}-PRKG", "tf_stall": "C-STDY-{n}-STAL", "tf_drive": "C-STDY-{n}-DRIV", "tf_label": "A-STDY-{n}-TEXT",
    },
}
_BAD_LAYER = re.compile(r"[<>/\\\":;?*|,=`]")


def apply_layer_names(cfg: Config, preset: str = "default", custom: dict[str, str] | None = None) -> list[str]:
    """Rename layers in place: preset first, then custom overrides. Custom
    keys may be our default layer names (SITE-PARCEL) or config keys
    (parcel). Returns warnings for anything skipped."""
    warnings: list[str] = []
    defaults = {st.name.upper(): k for k, st in cfg.layers.items()}
    for k, name in PRESETS.get(preset or "default", {}).items():
        if k in cfg.layers:
            cfg.layers[k].name = name
    for raw_key, raw_name in (custom or {}).items():
        key = str(raw_key).strip()
        name = str(raw_name).strip()
        k = key if key in cfg.layers else defaults.get(key.upper())
        if k is None:
            # Slope bands are named from the slope layer; allow SITE-SLOPE-* as an alias for it.
            warnings.append(f"Unknown layer '{key}' in the custom mapping; ignored.")
            continue
        if not name or len(name) > 255 or _BAD_LAYER.search(name.replace("{n}", "")):
            warnings.append(f"Layer name '{name}' for {key} isn't valid in AutoCAD; kept '{cfg.layers[k].name}'.")
            continue
        if k.startswith("tf_") and "{n}" not in name:
            name = name + "-{n}"  # one layer set per test-fit option
        cfg.layers[k].name = name
    names = [st.name for st in cfg.layers.values()]
    dups = {n for n in names if names.count(n) > 1}
    if dups:
        warnings.append(f"Several layers share a name ({', '.join(sorted(dups))}); their linework will be merged on that layer.")
    return warnings
