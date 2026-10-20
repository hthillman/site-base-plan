"""`sitekit` command line."""

from __future__ import annotations

import argparse
import sys

from .pipeline import Options, run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sitekit", description="US site base plan from an address or parcel number.")
    p.add_argument("query", help='street address ("123 Main St, Olympia, WA") or parcel number (APN)')
    p.add_argument("--buffer", type=float, default=100.0, help="buffer around the parcel, feet (default 100)")
    p.add_argument("--interval", type=float, default=2.0, choices=[1.0, 2.0, 5.0], help="contour interval, feet (default 2)")
    p.add_argument("--state", help="two-letter state; needed for parcel numbers outside WA, optional hint for addresses")
    p.add_argument("--county", help="county name, to disambiguate an APN")
    p.add_argument("--crs", type=int, help="force a coordinate system WKID (default: the site's State Plane zone in feet)")
    p.add_argument("--layers", help="path to a layers.toml (default: config/layers.toml)")
    p.add_argument("--out", default="out", help="output folder (default ./out)")
    p.add_argument("--also", action="append", default=[], help="another address or parcel number to combine into the same site (repeatable, up to 5 parcels)")
    p.add_argument("--layer-preset", choices=["default", "ncs"], default="default", help="CAD layer naming: default SITE-* or NCS-style")
    p.add_argument("--dwg", action="store_true", help="also write DWG (needs ODA File Converter or LibreDWG installed; DXF opens in AutoCAD directly)")
    a = p.parse_args(argv)
    try:
        res = run(a.query, Options(buffer_ft=a.buffer, contour_interval=a.interval, county=a.county, state=a.state, epsg=a.crs,
                                   layers_file=a.layers, out_dir=a.out, dwg=a.dwg,
                                   extra_queries=a.also, layer_preset=a.layer_preset))
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    print()
    for f in res.flags:
        print(f"[{f['level'].upper():7}] {f['text']}")
    print()
    for k, v in res.files.items():
        print(f"{k:16} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
