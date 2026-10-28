"""Web UI. Local: `sitekit-web` -> http://127.0.0.1:5055. On Vercel the same
Flask app runs as one function (api/index.py); outputs go to Vercel Blob
because function responses are capped at 4.5 MB and /tmp doesn't persist."""

from __future__ import annotations

import hmac
import importlib.util
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
from .parcel import jurisdiction_at, looks_like_apn
from .pipeline import Options, run, zoning_coverage

ON_VERCEL = bool(os.environ.get("VERCEL"))
OUT = Path("/tmp/sitekit-out") if ON_VERCEL else REPO_ROOT / "out"
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ACCESS_CODE = os.environ.get("ACCESS_CODE")  # shared code; unset = open
PRIVATE_TOKEN = os.environ.get("PRIVATE_READ_WRITE_TOKEN")
TERMS_ON = importlib.util.find_spec("sitekit.terms") is not None and importlib.import_module("sitekit.terms").READY  # private Blob store: feedback

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or "dev-only-secret"
app.config.update(SESSION_COOKIE_SECURE=bool(os.environ.get("SECRET_KEY")), SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_HTTPONLY=True, PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 180)

from .accounts import bp as accounts_bp  # noqa: E402

app.register_blueprint(accounts_bp)

from .mcp import bp as mcp_bp  # noqa: E402  (AI assistants: ChatGPT, Claude)

app.register_blueprint(mcp_bp)

try:  # Pro subscription (hosted site only)
    from .billing import bp as _billing_bp

    app.register_blueprint(_billing_bp)
except ImportError:
    pass

try:  # Pro firm (hosted site only)
    from .firm import bp as _firm_bp

    app.register_blueprint(_firm_bp)
except ImportError:
    pass

try:  # Pro batch (hosted site only)
    from .batch import bp as _batch_bp

    app.register_blueprint(_batch_bp)
except ImportError:
    pass

try:  # Terms of Service (hosted site only)
    from .terms import bp as _terms_bp

    app.register_blueprint(_terms_bp)
except ImportError:
    pass

try:  # /zoning coverage page (hosted site only: the zoning registry isn't in the open-source mirror)
    from .zoning.coverage_page import bp as _zoning_page_bp

    app.register_blueprint(_zoning_page_bp)
    ZONING_PAGE = True
except ImportError:
    ZONING_PAGE = False

try:  # IndexNow key file (hosted site only)
    from .indexnow import bp as _indexnow_bp

    app.register_blueprint(_indexnow_bp)
except ImportError:
    pass

try:  # hello@basesheet.site forwarding (hosted site only)
    from .inbound import bp as _inbound_bp

    app.register_blueprint(_inbound_bp)
except ImportError:
    pass

try:  # one-time setup endpoints (hosted site only; removed after use)
    from .admin_setup import bp as _admin_bp

    app.register_blueprint(_admin_bp)
except ImportError:
    pass

# Old hostnames (e.g. site-toolkit.vercel.app) that should 301 to SITE_URL. Pages only; /api keeps
# working everywhere so runs started on an old tab still finish.
REDIRECT_HOSTS = {h.strip().lower() for h in os.environ.get("REDIRECT_HOSTS", "").split(",") if h.strip()}


@app.before_request
def redirect_old_hosts():
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if site and request.host.lower() in REDIRECT_HOSTS and not request.path.startswith("/api/"):
        from flask import redirect

        qs = request.query_string.decode()
        return redirect(f"{site}{request.path}" + (f"?{qs}" if qs else ""), code=301)
LOCAL_RUNS: dict[str, Path] = {}  # run id -> folder, for local file serving

CONTENT_TYPES = {".pdf": "application/pdf", ".dxf": "application/dxf", ".dwg": "application/acad", ".png": "image/png",
                 ".tif": "image/tiff", ".json": "application/json", ".md": "text/markdown", ".toml": "text/plain",
                 ".pgw": "text/plain", ".zip": "application/zip"}


def _zip_bytes(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        from .config import FILE_NOTICE

        z.comment = FILE_NOTICE.encode()  # shown by most unzip tools
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


LOCAL_RESULTS: dict[str, dict] = {}


def save_result(run_id: str, result: dict) -> None:
    """Keep a run's result next to its files (same 2-day cleanup) so /r/<run_id> can show it later. Never raises."""
    try:
        if not BLOB_TOKEN:
            LOCAL_RESULTS[run_id] = result
            return
        blob_put(f"runs/r-{run_id}/result.json", json.dumps(result).encode(), "application/json")
    except Exception as e:  # noqa: BLE001
        print(f"WARN result save failed: {e}", flush=True)


def load_result(run_id: str) -> dict | None:
    if not BLOB_TOKEN:
        return LOCAL_RESULTS.get(run_id)
    from .http import session

    d = session().get("https://blob.vercel-storage.com", params={"prefix": f"runs/r-{run_id}/", "limit": 5},
                      headers={"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "7"}, timeout=30).json()
    b = next((b for b in d.get("blobs", []) if b["pathname"].endswith("/result.json")), None)
    if not b:
        return None
    r = session().get(b["url"], timeout=30)
    return r.json() if r.ok else None


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
        if "preview" in names:
            urls["preview"] = blob_put(f"{prefix}/{names['preview']}", (folder / names["preview"]).read_bytes(), "image/png")
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


OPTIONAL_LAYERS = {"aerial", "soils", "flood", "wetland", "massing"}


@app.post("/api/run")
def start():
    return run_request(request.get_json(force=True))


def run_request(d: dict, batch: bool = False):
    """Start a run and stream its progress. Shared by /api/run and Pro batch runs (/api/batch/run)."""
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
        skip={k for k in (d.get("skip") or []) if k in OPTIONAL_LAYERS},
    )
    blocked = plan_allowance(d, request.headers.get("X-Live-Check", ""))
    if blocked:
        return jsonify(blocked), 402
    if opts.testfit and not pro_ok():
        return jsonify(error="The test fit is part of Basesheet Pro. Sign in and subscribe on basesheet.site/pro, or build without it.", pro=True), 402
    try:  # Pro firm branding: title block and office layer standard (hosted site only)
        from .accounts import current_user
        from .firm import apply_to

        apply_to(opts, current_user(), parse_layer_map)
    except ImportError:
        pass
    if opts.firm and d.get("project"):
        opts.firm["project"] = str(d["project"]).strip()[:80]
    run_id = uuid.uuid4().hex[:10]
    events: queue.Queue = queue.Queue()
    _tok = os.environ.get("ADMIN_TOKEN", "")
    base = {"live_check": True} if _tok and hmac.compare_digest(request.headers.get("X-Live-Check", ""), _tok) else {}
    if batch:
        base["batch"] = True
    if opts.firm:
        base["firm"] = True
    # Repeat use without an ID: the browser's own count of earlier plans and days since its first.
    def _int(v, hi):
        try:
            return max(0, min(hi, int(v)))
        except (TypeError, ValueError):
            return None
    base["prior"], base["since"] = _int(d.get("prior"), 9999) or 0, _int(d.get("since"), 3650)
    base["mprior"] = _int(d.get("mprior"), 9999) or 0  # this browser's plans earlier this month

    from .accounts import current_user as _cu

    _u = _cu()
    user_id = _u["id"] if _u else None  # read now: the worker thread has no request context

    def worker():
        t0 = time.time()
        try:
            res = run(q, opts, log=lambda m: events.put({"log": m}))
            events.put({"log": "Publishing files"})
            urls = publish(run_id, res.out_dir, res.files)
            rec = {
                **base, "outcome": "ok", "input": "apn" if looks_like_apn(q) else "address", "state": res.site.state,
                "parcels": len(res.site.parcels) or (1 if res.site.parcel is not None else 0), "layers": opts.layer_preset + ("+custom" if opts.layer_custom else ""),
                "parcel": res.site.parcel is not None, "testfit": getattr(res.testfit, "status", None), "zoning": zoning_coverage(res),
                "seconds": round(time.time() - t0, 1), "interval": opts.contour_interval,
                "t": {k: round(v, 1) for k, v in res.timings.items()},  # per stage, to find what makes a run slow
                "failed_layers": sorted(k for k, lr in res.layers.items() if lr.status == "failed"),
                "dem_res_m": res.layers["dem"].extra.get("source_res_m") if res.layers.get("dem") else None,
                "zoning_where": sorted({d.get("jurisdiction") for d in (res.zoning or {}).get("details", []) if d.get("jurisdiction")}),
            }
            rj = {"flags": res.flags, "files": urls, "seconds": round(res.timings.get("total", 0)), "state": res.site.state,
                  "zoning": res.zoning, "run_id": run_id, "title": res.site.matched_address, "facts": res.facts}
            save_result(run_id, rj)
            count_plan(user_id)
            events.put({"result": rj})
            # After the result is out, so it never slows a plan: which local government the run was in (city or
            # township and county, from Census), to see where zoning coverage is missing. Never the address.
            record_usage({**rec, "jurisdiction": jurisdiction_at(res.site.lon, res.site.lat)})
        except Exception as e:  # noqa: BLE001
            record_usage({**base, "outcome": "error", "input": "apn" if looks_like_apn(q) else "address", "state": opts.state or "",
                          "error_kind": type(e).__name__, "error": str(e)[:160] if type(e).__name__ != "GeocodeError" else "",
                          "where": crash_site(e),
                          "hint": getattr(e, "hint", ""), "shape": query_shape(q) if type(e).__name__ == "GeocodeError" else None,
                          "seconds": round(time.time() - t0, 1)})
            events.put({"error": str(e), "suggestions": getattr(e, "suggestions", []), "near": getattr(e, "near", None),
                        "pick": type(e).__name__ == "GeocodeError" and not getattr(e, "hint", "").startswith("multi")})
        events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        # One JSON object per line; the page renders progress as it arrives.
        while (ev := events.get()) is not None:
            yield json.dumps(ev) + "\n"

    return Response(stream(), mimetype="application/x-ndjson", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})


def pro_ok() -> bool:
    """Pro features allowed for this request: always, until Pro is on sale (and in the open-source build)."""
    try:
        from . import billing
    except ImportError:
        return True
    if not billing.live():
        return True
    from .accounts import current_user

    return billing.is_pro(current_user())


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


def crash_site(e: BaseException) -> str:
    """'pipeline.py:348 in compute_flags' for the deepest sitekit frame, so a usage record says where a run broke."""
    import traceback

    frames = [f for f in traceback.extract_tb(e.__traceback__) if "sitekit" in f.filename]
    if not frames or type(e).__name__ == "GeocodeError":
        return ""
    f = frames[-1]
    return f"{Path(f.filename).name}:{f.lineno} in {f.name}"


def query_shape(q: str) -> dict:
    """What a failed query looked like, without keeping it: enough to see why lookups miss."""
    import re

    t = q.strip()
    return {"words": len(t.split()), "has_number": bool(re.search(r"\d", t)), "starts_with_number": bool(re.match(r"\d", t)),
            "has_zip": bool(re.search(r"\b\d{5}(-\d{4})?\b", t)), "has_comma": "," in t,
            "has_unit": bool(re.search(r"(?i)\b(apt|unit|suite|ste|#|lot|bldg)\b|#", t)),
            "has_state": bool(re.search(r"\b[A-Z]{2}\b", t)), "looks_like_apn": looks_like_apn(t)}


def record_usage(rec: dict) -> None:
    """One anonymous record per run (no address, no location below state).
    Never raises: usage logging must not break a run."""
    from datetime import datetime, timezone

    try:
        now = datetime.now(timezone.utc)
        private_put(f"usage/{now:%Y-%m-%d}", {"at": now.isoformat(timespec="seconds"), **rec})
    except Exception as e:  # noqa: BLE001
        print(f"WARN usage record failed: {e}", flush=True)


# Monthly allowance (off unless FREE_PLANS_PER_MONTH is set): signed-in free accounts are counted on the server;
# without an account the browser's own count applies (soft: it prompts a free sign-in rather than policing).
# Pro accounts, batch runs and the live check are exempt; AI assistants have their own daily cap (mcp.py).
FREE_PLANS_PER_MONTH = int(os.environ.get("FREE_PLANS_PER_MONTH", "0") or 0)
ANON_PLANS_PER_MONTH = int(os.environ.get("ANON_PLANS_PER_MONTH", "0") or 0)


def _month() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m")


def count_private(prefix: str) -> int:
    """How many private records sit under a prefix (no reads)."""
    from .http import session

    if not PRIVATE_TOKEN:
        folder = LOCAL_INBOX / prefix
        return len(list(folder.glob("*.json"))) if folder.exists() else 0
    n, cursor = 0, None
    while True:
        d = session().get("https://blob.vercel-storage.com", params={"prefix": prefix + "/", "limit": 1000, **({"cursor": cursor} if cursor else {})},
                          headers={"authorization": f"Bearer {PRIVATE_TOKEN}", "x-api-version": "7"}, timeout=30).json()
        n += len(d.get("blobs", []))
        cursor = d.get("cursor")
        if not d.get("hasMore"):
            return n


def _is_pro() -> bool:
    try:
        from . import billing
    except ImportError:
        return False
    from .accounts import current_user

    return billing.live() and billing.is_pro(current_user())


def plan_allowance(d: dict, live_check_header: str) -> dict | None:
    """None if this run may go ahead; otherwise the JSON for a 402 that the page turns into a sign-in / upgrade box."""
    if not FREE_PLANS_PER_MONTH:
        return None
    tok = os.environ.get("ADMIN_TOKEN", "")
    if (tok and hmac.compare_digest(live_check_header, tok)) or _is_pro():
        return None
    from .accounts import can_sign_up, current_user

    u = current_user()
    nxt = _next_month_label()
    if u:
        used = count_private(f"planq/{u['id']}/{_month()}")
        if used < FREE_PLANS_PER_MONTH:
            return None
        return {"limit": "account", "allowance": FREE_PLANS_PER_MONTH, "resets": nxt,
                "error": f"You've used this month's {FREE_PLANS_PER_MONTH} free plans. Your allowance resets on {nxt}."}
    try:
        mprior = int(d.get("mprior") or 0)
    except (TypeError, ValueError):
        mprior = 0
    if not ANON_PLANS_PER_MONTH or mprior < ANON_PLANS_PER_MONTH or not can_sign_up():
        return None
    return {"limit": "anon", "allowance": FREE_PLANS_PER_MONTH, "anon_allowance": ANON_PLANS_PER_MONTH,
            "error": f"You've made {ANON_PLANS_PER_MONTH} plan{'s' if ANON_PLANS_PER_MONTH != 1 else ''} this month. "
                     f"Sign in free to keep going: {FREE_PLANS_PER_MONTH} plans a month, no password."}


def _next_month_label() -> str:
    from datetime import date

    t = date.today()
    first = date(t.year + (t.month == 12), t.month % 12 + 1, 1)
    return first.strftime("%B %-d")


def count_plan(user_id: str | None) -> None:
    """Record one successful plan against a signed-in account's monthly allowance. Never raises."""
    if not (FREE_PLANS_PER_MONTH and user_id):
        return
    try:
        private_put(f"planq/{user_id}/{_month()}", {"n": 1})
    except Exception as e:  # noqa: BLE001
        print(f"WARN plan count failed: {e}", flush=True)


def private_put(prefix: str, record: dict) -> None:
    """Write one JSON record to the private Blob store (not publicly readable)."""
    from datetime import datetime, timezone

    from .http import session

    if not PRIVATE_TOKEN:
        folder = LOCAL_INBOX / prefix  # same layout as the hosted store: <prefix>/<file>.json
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{uuid.uuid4().hex[:8]}.json").write_text(json.dumps(record, indent=2))
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
    email = str(d.get("email") or "").strip()[:254]
    if email and not EMAIL_RE.match(email):
        return jsonify(error="That doesn't look like an email address."), 400
    if email:
        notify(f"Feature vote with email: {choice}" + (f" ({str(d.get('detail') or '')[:80]})" if d.get("detail") else ""))
    private_put("interest", {"choice": choice, "detail": str(d.get("detail") or "").strip()[:300], "email": email,
                             "state": str(d.get("state") or "")[:2], "vote_id": str(d.get("vote_id") or "")[:16],
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return jsonify(ok=True)


EVENT_NAMES = {"ai_setup", "ask_shown", "ask_sent", "limit_hit", "run_start", "run_done", "run_error", "download_zip", "open_pdf", "save_click", "save_link_sent",
               "tip_click", "firms_click", "vote", "vote_email", "map_pick"}


@app.post("/api/event")
def event():
    """Anonymous click counter for the funnel (event name + the site's state, nothing else). Never fails loudly."""
    from datetime import datetime, timezone

    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("e") or "")
    if name not in EVENT_NAMES or request.headers.get("X-Live-Check"):
        return ("", 204)
    try:
        private_put("events", {"e": name, "state": str(d.get("state") or "")[:2], "choice": str(d.get("choice") or "")[:16],
                               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    except Exception as e:  # noqa: BLE001
        print(f"WARN event failed: {e}", flush=True)
    return ("", 204)


FIRM_WANTS = {"zoning", "batch", "standards", "coverage", "massing"}
NOTIFY_URL = os.environ.get("NOTIFY_URL", "")  # optional: ntfy.sh topic, Slack or Discord webhook, pinged on firm signups


def notify(text: str) -> None:
    """Best-effort ping to the site owner. Never includes email addresses. Never raises."""
    if not NOTIFY_URL:
        return
    from .http import session

    try:
        if "hooks.slack.com" in NOTIFY_URL:
            session().post(NOTIFY_URL, json={"text": text}, timeout=5)
        elif "discord.com/api/webhooks" in NOTIFY_URL:
            session().post(NOTIFY_URL, json={"content": text}, timeout=5)
        else:
            session().post(NOTIFY_URL, data=text.encode(), headers={"Title": "Basesheet"}, timeout=5)
    except Exception as e:  # noqa: BLE001
        print(f"WARN notify failed: {e}", flush=True)


@app.post("/api/firms")
def firm_interest():
    """Firm interest from the For firms page (stored privately)."""
    from datetime import datetime, timezone

    from .pages import FIRMS_PAGE

    if not FIRMS_PAGE:
        abort(404)
    d = request.get_json(force=True, silent=True) or {}
    if d.get("website"):
        return jsonify(ok=True)
    email = str(d.get("email") or "").strip()[:254]
    if not EMAIL_RE.match(email):
        return jsonify(error="That doesn't look like an email address."), 400
    want = [w for w in (d.get("want") or []) if w in FIRM_WANTS]
    use = str(d.get("use") or d.get("notes") or "").strip()[:2000]  # the short form asks only for email, a use line and interests
    source = d.get("source") if d.get("source") in ("third_plan", "assistant") else "firms_page"
    private_put("firms", {"email": email, "use": use, "want": want, "source": source, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    where = {"third_plan": "after their third plan", "assistant": "from a ChatGPT/Claude result"}.get(source, "on the For firms page")
    notify(f"New early-access email {where}: {email}; wants {', '.join(want) or 'nothing picked'}; use: {use[:200] or '-'}")
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


@app.get("/r/<run_id>")
def result_page(run_id):
    """A finished run's result page, shareable for as long as its files are kept (2 days)."""
    import re

    from .pages import index as page
    from .parcel import supported_states

    if not re.fullmatch(r"[0-9a-f]{10}", run_id):
        abort(404)
    rj = load_result(run_id) or {"expired": True}
    resp = Response(page(supported_states(), bool(ACCESS_CODE), preload=rj))
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@app.get("/about")
def about():
    from .pages import about as page
    from .parcel import supported_states

    return page(supported_states())


@app.get("/sources")
def sources():
    from .pages import sources as page

    return page()


@app.get("/pro")
def pro_page():
    from flask import redirect

    try:
        from . import billing
    except ImportError:
        billing = None
    if billing is None or not billing.live():
        return redirect("/firms", code=302)
    from .pages import pro

    return pro(billing.prices())


@app.get("/firms")
def firms_page():
    from .pages import FIRMS_PAGE, firms

    if not FIRMS_PAGE:
        abort(404)
    return firms()


@app.get("/plans")
def plans_page():
    from .accounts import enabled
    from .pages import plans

    if not enabled():
        abort(404)
    return plans()


@app.get("/privacy")
def privacy():
    from .pages import privacy as page

    return page()


STATIC_DIR = Path(__file__).parent / "static"


def _site_url() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/") or request.host_url.rstrip("/")


@app.get("/guides")
def guides_index():
    from .guides import guides_index as page

    return page()


@app.get("/guides/<slug>")
def guide(slug):
    from .guides import guide_page

    html = guide_page(slug)
    return html if html else abort(404)


@app.get("/parcels")
def parcels_index():
    from .guides import parcels_index as page

    return page()


@app.get("/parcels/<slug>")
def parcels_state(slug):
    from .guides import parcel_state_page

    html = parcel_state_page(slug)
    return html if html else abort(404)


@app.get("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {_site_url()}/sitemap.xml\n", mimetype="text/plain")


@app.get("/favicon.svg")
@app.get("/favicon.ico")
def favicon():
    r = send_file(STATIC_DIR / "favicon.svg", mimetype="image/svg+xml")
    r.headers["Cache-Control"] = "public, max-age=604800"
    return r


@app.get("/BingSiteAuth.xml")
def bing_site_auth():
    f = STATIC_DIR / "BingSiteAuth.xml"  # hosted site only; not in the open-source mirror
    return send_file(f, mimetype="application/xml") if f.exists() else abort(404)


@app.get("/og.png")
def og_image():
    r = send_file(STATIC_DIR / "og.png", mimetype="image/png")
    r.headers["Cache-Control"] = "public, max-age=604800"
    return r


@app.get("/sitemap.xml")
def sitemap():
    from .pages import FIRMS_PAGE

    base = _site_url()
    from .guides import all_paths

    paths = ["/", "/about", "/sources", "/privacy"] + (["/terms"] if TERMS_ON else []) + (["/zoning"] if ZONING_PAGE else []) + (["/firms"] if FIRMS_PAGE else []) + all_paths()
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, mimetype="application/xml")


@app.get("/llms.txt")
def llms_txt():
    from .pages import REPO_URL
    from .parcel import all_sources, county_sources

    from .guides import GUIDES

    base = _site_url()
    guides = "\n".join(f"- [{g.h1}]({base}/guides/{g.slug}): {g.description}" for g in GUIDES)
    states = ", ".join(sorted(all_sources()))
    counties = sum(len(v) for v in county_sources().values())
    cstates = ", ".join(sorted(county_sources()))
    text = f"""# Basesheet

> Basesheet is a free web tool that builds planning-level site context from public data for any US street address or parcel number: parcel lines, LiDAR contours, slopes, soils, FEMA flood zones, wetlands, roads and aerial imagery, delivered as CAD, 3D, GIS and PDF files, plus the zoning district and its rules in covered cities and counties. Outputs are not a survey and not for permit submission. No account. Open source (MIT).

Built for landscape architects, site designers and civil engineers doing early site studies, feasibility and concept design. It replaces the hour or two of pulling public GIS layers into CAD by hand. It is not a survey.

## Pages
- [Home: build a base plan]({base}/): enter an address or parcel number; results in about 15-30 seconds as a zip
- [About, coverage and FAQ]({base}/about): what it does, limits, state-by-state parcel coverage, common questions
- [Data sources]({base}/sources): every public data source, with publisher and resolution
- [Privacy]({base}/privacy)
- [Use Basesheet in ChatGPT and Claude]({base}/guides/use-in-chatgpt-and-claude): add the MCP server as a custom connector (Claude Settings > Connectors; ChatGPT Developer mode); no auth or key
- [MCP server]({base}/mcp): Streamable HTTP endpoint (no auth) with one tool, build_base_plan(site), for ChatGPT, Claude and other MCP clients; returns key facts, a preview map and a result page link
- [Source code]({REPO_URL}): MIT-licensed Python core and the parcel source registry
- [Free zoning lookup]({base}/zoning): every city and county where Basesheet finds the zoning district for an address, with rule summaries (setbacks, height, density, parking) where drafted; not a zoning determination
- [Free parcel data by state]({base}/parcels): every verified free statewide parcel layer, with publisher, coverage, vintage, fields and REST endpoint

## Guides
{guides}

## Outputs
- DXF in State Plane feet (AutoCAD, Civil 3D), plus a copy near 0,0 for SketchUp; layer names configurable (default or US National CAD Standard)
- Textured 3D terrain (COLLADA .dae and OBJ) for SketchUp, Rhino, Blender, with existing buildings as 3D massing blocks (FEMA USA Structures heights) and, where zoning rules exist, the zoning envelope
- LandXML surface (Civil 3D), GeoTIFF elevation model, GeoJSON layers, KML for Google Earth
- PDF with scaled sheets and plain-language site flags (floodplain, wetlands, steep slopes, soils)
- Provenance file listing each layer's source, date and resolution, and any layer that failed

## Data
- Topography: USGS 3DEP (1 m LiDAR where available, otherwise 3 m or 10 m; contour interval adapts)
- Soils: USDA NRCS SSURGO
- Flood: FEMA National Flood Hazard Layer
- Wetlands: USFWS National Wetlands Inventory
- Roads: US Census TIGER; aerial: Esri World Imagery
- Parcels: free statewide layers in {states}, plus {counties} county layers in {cstates}. Elsewhere the plan is drawn around the address without a parcel line. Full list: {base}/parcels

## Limits
- Planning-level only. Parcel lines are assessor tax lines, often 5-50 ft off the legal boundary. Wetland and flood layers are screening maps. Confirm with a licensed surveyor and specialists.
- One site up to 5 adjoining parcels / 20 acres per run.
"""
    return Response(text, mimetype="text/plain")


def main():
    import argparse

    p = argparse.ArgumentParser(prog="sitekit-web")
    p.add_argument("--port", type=int, default=5055)
    a = p.parse_args()
    print(f"Basesheet UI: http://127.0.0.1:{a.port}")
    app.run(host="127.0.0.1", port=a.port, debug=False)


if __name__ == "__main__":
    main()
