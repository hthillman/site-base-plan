"""Web UI. Local: `sitekit-web` -> http://127.0.0.1:5055. On Vercel the same
Flask app runs as one function (api/index.py); outputs go to Vercel Blob
because function responses are capped at 4.5 MB and /tmp doesn't persist."""

from __future__ import annotations

import hmac
import io
import json
import time
import os
import queue
import threading
import uuid
import zipfile
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from .config import REPO_ROOT
from .parcel import looks_like_apn
from .pipeline import Options, run

ON_VERCEL = bool(os.environ.get("VERCEL"))
OUT = Path("/tmp/sitekit-out") if ON_VERCEL else REPO_ROOT / "out"
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ACCESS_CODE = os.environ.get("ACCESS_CODE")  # shared code; unset = open
PRIVATE_TOKEN = os.environ.get("PRIVATE_READ_WRITE_TOKEN")  # private Blob store: feedback

app = Flask(__name__)
LOCAL_RUNS: dict[str, Path] = {}  # run id -> folder, for local file serving

CONTENT_TYPES = {".pdf": "application/pdf", ".dxf": "application/dxf", ".dwg": "application/acad", ".png": "image/png",
                 ".tif": "image/tiff", ".json": "application/json", ".md": "text/markdown", ".toml": "text/plain",
                 ".pgw": "text/plain", ".zip": "application/zip"}


def _zip_bytes(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, f"{folder.name}/{p.relative_to(folder)}")
    return buf.getvalue()


def blob_put(pathname: str, data: bytes, content_type: str) -> str:
    """Vercel Blob REST upload; returns the public URL."""
    from .http import session

    r = session().put(
        f"https://blob.vercel-storage.com/{pathname}",
        data=data,
        headers={"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7", "x-content-type": content_type,
                 "x-add-random-suffix": "0", "x-allow-overwrite": "1"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["url"]


def publish(run_id: str, folder: Path, files: dict[str, str]) -> dict[str, str]:
    """Map output keys to downloadable URLs (Blob when deployed, local otherwise)."""
    names = {k: Path(v).name for k, v in files.items()}
    if not BLOB_TOKEN:
        LOCAL_RUNS[run_id] = folder
        urls = {k: f"/files/{run_id}/{n}" for k, n in names.items()}
        urls["zip"] = f"/zip/{run_id}"
        return urls
    # The zip (everything) plus a separate PDF copy for in-browser viewing.
    prefix = f"runs/{folder.name}-{run_id}"
    data = _zip_bytes(folder)
    path = f"{prefix}/{folder.name}.zip"
    def put_all():
        urls = {"zip": blob_put(path, data, "application/zip")}
        if "pdf" in names:  # separate copy so the PDF opens in the browser
            urls["pdf"] = blob_put(f"{prefix}/{names['pdf']}", (folder / names["pdf"]).read_bytes(), "application/pdf")
        return urls

    try:
        return put_all()
    except Exception as e:  # noqa: BLE001
        if "quota" not in str(getattr(getattr(e, "response", None), "text", "")).lower():
            raise
        # Storage full: drop the oldest runs, then try once more.
        freed = prune_runs(older_than_hours=6)
        print(f"WARN blob quota hit; pruned {freed} old files", flush=True)
        try:
            return put_all()
        except Exception:  # noqa: BLE001
            raise RuntimeError("The site is over its free storage limit right now, so files can't be saved. "
                               "Please try again later.") from None


def prune_runs(older_than_hours: float) -> int:
    """Delete published run files older than N hours. Returns files deleted."""
    from datetime import datetime, timedelta, timezone

    from .http import session

    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    auth = {"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"}
    old, cursor = [], None
    while True:
        params = {"prefix": "runs/", "limit": 1000, **({"cursor": cursor} if cursor else {})}
        d = session().get("https://blob.vercel-storage.com", params=params, headers=auth, timeout=60).json()
        old += [b["url"] for b in d.get("blobs", []) if datetime.fromisoformat(b["uploadedAt"].replace("Z", "+00:00")) < cutoff]
        cursor = d.get("cursor")
        if not d.get("hasMore"):
            break
    for i in range(0, len(old), 100):
        session().post("https://blob.vercel-storage.com/delete", json={"urls": old[i:i + 100]}, headers=auth, timeout=60).raise_for_status()
    return len(old)


KEEP_HOURS = 48  # Pro plan: storage is metered (~$0.02/GB-month), so 2 days is cheap


@app.get("/api/cleanup")
def cleanup():
    """Daily Vercel cron: delete published runs older than KEEP_HOURS."""
    secret = os.environ.get("CRON_SECRET")
    if not secret or request.headers.get("authorization") != f"Bearer {secret}":
        abort(401)
    if not BLOB_TOKEN:
        return jsonify(deleted=0)
    return jsonify(deleted=prune_runs(KEEP_HOURS))


@app.post("/api/run")
def start():
    d = request.get_json(force=True)
    if ACCESS_CODE and not hmac.compare_digest(str(d.get("code") or ""), ACCESS_CODE):
        return jsonify(error="Wrong or missing access code."), 401
    q = (d.get("query") or "").strip()
    if not q:
        return jsonify(error="Enter an address or parcel number."), 400
    opts = Options(
        buffer_ft=min(1000.0, max(0.0, float(d.get("buffer") or 100))),
        contour_interval=float(d.get("interval") or 2) if str(d.get("interval")) in ("1", "2", "5") else 2.0,
        county=(d.get("county") or None), state=(d.get("state") or None), out_dir=str(OUT),
        # LibreDWG's DWG writer produced files AutoCAD reports as corrupt; ship
        # DXF only (AutoCAD opens DXF natively) until a DWG path is verified.
        dwg=False,
        # Test fit is experimental (unreviewed draft zoning rules): off unless asked for.
        testfit=d.get("testfit") in (True, "true", "1", 1, "on"),
        extra_queries=[str(x).strip()[:200] for x in (d.get("also") or []) if str(x).strip()][:4],
        layer_preset="ncs" if d.get("layers") == "ncs" else "default",
        layer_custom=parse_layer_map(d.get("layer_map") or "") if d.get("layers") == "custom" else {},
    )
    run_id = uuid.uuid4().hex[:10]
    events: queue.Queue = queue.Queue()

    def worker():
        t0 = time.time()
        try:
            res = run(q, opts, log=lambda m: events.put({"log": m}))
            events.put({"log": "Publishing files"})
            urls = publish(run_id, res.out_dir, res.files)
            record_usage({
                "outcome": "ok", "input": "apn" if looks_like_apn(q) else "address", "state": res.site.state,
                "parcels": len(res.site.parcels) or (1 if res.site.parcel is not None else 0), "layers": opts.layer_preset + ("+custom" if opts.layer_custom else ""),
                "parcel": res.site.parcel is not None, "testfit": getattr(res.testfit, "status", None),
                "seconds": round(time.time() - t0, 1), "interval": opts.contour_interval,
                "failed_layers": sorted(k for k, lr in res.layers.items() if lr.status == "failed"),
                "dem_res_m": res.layers["dem"].extra.get("source_res_m") if res.layers.get("dem") else None,
            })
            events.put({"result": {"flags": res.flags, "files": urls, "seconds": round(res.timings.get("total", 0)), "state": res.site.state}})
        except Exception as e:  # noqa: BLE001
            record_usage({"outcome": "error", "input": "apn" if looks_like_apn(q) else "address", "state": opts.state or "",
                          "error_kind": type(e).__name__, "error": str(e)[:160] if type(e).__name__ != "GeocodeError" else "",
                          "seconds": round(time.time() - t0, 1)})
            events.put({"error": str(e)})
        events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        # One JSON object per line; the page renders progress as it arrives.
        while (ev := events.get()) is not None:
            yield json.dumps(ev) + "\n"

    return Response(stream(), mimetype="application/x-ndjson", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})


def parse_layer_map(text: str) -> dict[str, str]:
    """'SITE-PARCEL = L-PROP-LINE' lines -> {old: new}; unchanged lines dropped."""
    out = {}
    for line in str(text).splitlines()[:80]:
        if "=" not in line:
            continue
        old, new = (x.strip() for x in line.split("=", 1))
        if old and new and old != new:
            out[old[:255]] = new[:255]
    return out


def record_usage(rec: dict) -> None:
    """One anonymous record per run (no address, no location below state).
    Never raises: usage logging must not break a run."""
    from datetime import datetime, timezone

    try:
        now = datetime.now(timezone.utc)
        private_put(f"usage/{now:%Y-%m-%d}", {"at": now.isoformat(timespec="seconds"), **rec})
    except Exception as e:  # noqa: BLE001
        print(f"WARN usage record failed: {e}", flush=True)


def private_put(prefix: str, record: dict) -> None:
    """Write one JSON record to the private Blob store (not publicly readable)."""
    from datetime import datetime, timezone

    from .http import session

    if not PRIVATE_TOKEN:
        LOCAL_INBOX.mkdir(parents=True, exist_ok=True)
        (LOCAL_INBOX / f"{prefix}-{uuid.uuid4().hex[:8]}.json").write_text(json.dumps(record, indent=2))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    r = session().put(
        f"https://blob.vercel-storage.com/{prefix}/{stamp}.json",
        data=json.dumps(record).encode(),
        headers={"authorization": f"Bearer {PRIVATE_TOKEN}", "x-api-version": "7", "x-content-type": "application/json",
                 "x-add-random-suffix": "1", "x-vercel-blob-access": "private"},
        timeout=30,
    )
    r.raise_for_status()


LOCAL_INBOX = REPO_ROOT / "out" / "_inbox"
EMAIL_RE = __import__("re").compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


INTEREST_CHOICES = {"zoning", "batch", "titleblock", "county", "massing", "other"}


@app.post("/api/interest")
def interest():
    """One-click 'what should it do next' vote, shown after a successful run.
    Anonymous: the choice, an optional place/detail, and the run's state."""
    from datetime import datetime, timezone

    d = request.get_json(force=True, silent=True) or {}
    choice = str(d.get("choice") or "")
    if choice not in INTEREST_CHOICES:
        return jsonify(error="Unknown option."), 400
    private_put("interest", {"choice": choice, "detail": str(d.get("detail") or "").strip()[:300],
                             "state": str(d.get("state") or "")[:2], "vote_id": str(d.get("vote_id") or "")[:16],
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return jsonify(ok=True)


@app.post("/api/feedback")
def feedback():
    from datetime import datetime, timezone

    d = request.get_json(force=True, silent=True) or {}
    if d.get("website"):
        return jsonify(ok=True)
    msg = str(d.get("message") or "").strip()
    if len(msg) < 3:
        return jsonify(error="Write a few words first."), 400
    email = str(d.get("email") or "").strip()[:254]
    private_put("feedback", {"message": msg[:4000], "email": email if EMAIL_RE.match(email) else "",
                             "query": str(d.get("query") or "")[:200], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return jsonify(ok=True)


@app.post("/api/check")
def check_code():
    d = request.get_json(force=True, silent=True) or {}
    ok = not ACCESS_CODE or hmac.compare_digest(str(d.get("code") or ""), ACCESS_CODE)
    return jsonify(ok=ok), (200 if ok else 401)


@app.get("/files/<run_id>/<name>")
def file(run_id: str, name: str):
    folder = LOCAL_RUNS.get(run_id) or abort(404)
    p = (folder / name).resolve()
    if folder.resolve() not in p.parents or not p.exists():
        abort(404)
    return send_file(p, as_attachment=p.suffix in (".dxf", ".dwg", ".tif", ".json"))


@app.get("/zip/<run_id>")
def zipped(run_id: str):
    folder = LOCAL_RUNS.get(run_id) or abort(404)
    return send_file(io.BytesIO(_zip_bytes(folder)), mimetype="application/zip", as_attachment=True, download_name=f"{folder.name}.zip")


@app.get("/")
def index():
    from .pages import index as page
    from .parcel import supported_states

    return page(supported_states(), bool(ACCESS_CODE))


@app.get("/about")
def about():
    from .pages import about as page
    from .parcel import supported_states

    return page(supported_states())


@app.get("/sources")
def sources():
    from .pages import sources as page

    return page()


@app.get("/privacy")
def privacy():
    from .pages import privacy as page

    return page()


@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /api/\n", mimetype="text/plain")


def main():
    import argparse

    p = argparse.ArgumentParser(prog="sitekit-web")
    p.add_argument("--port", type=int, default=5055)
    a = p.parse_args()
    print(f"Site base plan UI: http://127.0.0.1:{a.port}")
    app.run(host="127.0.0.1", port=a.port, debug=False)


if __name__ == "__main__":
    main()
