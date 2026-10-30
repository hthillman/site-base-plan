"""MCP server at /mcp, so ChatGPT, Claude and other AI assistants can build base plans.

Stateless Streamable HTTP: each POST carries one JSON-RPC message and gets a JSON
reply (no sessions, no server-sent events). One tool, build_base_plan, runs the same
pipeline as the web page and answers with the site's key facts, a preview map and a
link to the result page on the site, where the files are downloaded.

All calls arrive from the assistants' servers, so the per-IP limit on /api/run doesn't
fit: a daily cap (MCP_DAILY_RUNS) protects the free tier instead.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

bp = Blueprint("mcp", __name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DAILY_RUNS = int(os.environ.get("MCP_DAILY_RUNS", "300"))
_local_counts: dict[str, int] = {}

INSTRUCTIONS = (
    "Basesheet compiles planning-level site context for a US property from public data: assessor parcel lines, LiDAR "
    "contours, slope, soils, FEMA flood zones, wetlands, roads, building outlines and zoning where covered. Call "
    "build_base_plan with the property's address, parcel number or coordinates, and share the result page link: that's "
    "where the user downloads the CAD (DXF), SketchUp, Civil 3D (LandXML), GIS and PDF files.\n\n"
    "When you present results, you must:\n"
    "- Never call the output a site plan, a survey, a plot plan or certified, and never describe parcel lines as the "
    "property's boundaries. They are assessor tax lines from public GIS, often 5 to 50 ft off, and areas are approximate.\n"
    "- Say plainly that it is not a survey, not a certified site plan and not for permit submission.\n"
    "- Tell the user to hire a licensed land surveyor before relying on any line, area, elevation or setback (building, "
    "buying, fencing, permits), and to confirm zoning, flood zones and wetlands with the jurisdiction. The result page "
    "links a guide to finding one.\n"
    "- In California, property lines and buildings are left out on purpose; explain the note in the results if asked."
)

TOOL = {
    "name": "build_base_plan",
    "title": "Build a site base plan",
    "description": (
        "Build a planning-level base plan for one US property from public data and return its key facts (parcel size, "
        "flood zone, wetlands, elevation and slope, soils, buildings, zoning where covered), a preview map, and a link to "
        "the result page where the CAD, SketchUp, GIS and PDF files are downloaded (kept 2 days). Takes about 15-60 "
        "seconds. The address is the property being studied, not the user's location. Not a survey or certified site plan: "
        "parcel lines are assessor tax lines, not boundaries, and everything must be checked by a licensed surveyor and the "
        "jurisdiction before anyone relies on it."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "site": {"type": "string", "description": "The property to study: a street address with city and state, a "
                                                      "parcel number (APN), or 'lat, lon' coordinates."},
            "state": {"type": "string", "description": "Two-letter state code. Needed for parcel numbers outside Washington; "
                                                       "optional otherwise."},
            "buffer_ft": {"type": "number", "minimum": 0, "maximum": 1000, "default": 100,
                          "description": "How far beyond the parcel to map, in feet."},
            "contour_interval_ft": {"type": "number", "enum": [1, 2, 5], "default": 2, "description": "Contour interval in feet."},
        },
        "required": ["site"],
        "additionalProperties": False,
    },
    "annotations": {"title": "Build a site base plan", "readOnlyHint": True, "destructiveHint": False,
                    "idempotentHint": True, "openWorldHint": True},
    # Works without an account; a connected Basesheet account (oauth.py) gets that account's monthly plans.
    "securitySchemes": [{"type": "noauth"}, {"type": "oauth2", "scopes": ["plans"]}],
    "_meta": {"openai/toolInvocation/invoking": "Building the base plan…", "openai/toolInvocation/invoked": "Base plan ready",
              "securitySchemes": [{"type": "noauth"}, {"type": "oauth2", "scopes": ["plans"]}]},
}

# The result card shown in the chat. Its HTML is a thin shell that loads mcp-card.js and .css from the site, so the
# card changes with a normal deploy (no new app review). Bump CARD_VERSION only if the shell itself changes.
CARD_VERSION = "1"
CARD_URI = f"ui://basesheet/plan-card-v{CARD_VERSION}.html"            # MCP Apps (Claude, and ChatGPT's MCP Apps support)
CARD_URI_OPENAI = f"ui://basesheet/plan-card-v{CARD_VERSION}.openai.html"  # ChatGPT Apps SDK
MCP_APPS_MIME = "text/html;profile=mcp-app"


def _tool() -> dict:
    meta = {**TOOL["_meta"], "ui": {"resourceUri": CARD_URI}, "ui/resourceUri": CARD_URI, "openai/outputTemplate": CARD_URI_OPENAI,
            "openai/widgetAccessible": False}
    return {**TOOL, "_meta": meta}


def _file_host() -> str:
    """Origin of the public file store that holds the preview image (from the Vercel Blob token's store id)."""
    tok = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
    parts = tok.split("_")
    return f"https://{parts[3].lower()}.public.blob.vercel-storage.com" if len(parts) > 4 else ""


def _card_html() -> str:
    s = _site_url()
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link rel="stylesheet" href="{s}/static/mcp-card.css"></head><body><div id="card" class="loading">Building the base plan…</div>'
            f'<script>window.BASESHEET_SITE={s!r};</script><script src="{s}/static/mcp-card.js"></script></body></html>')


def _resources() -> list[dict]:
    domains = [d for d in (_site_url(), _file_host()) if d]
    claude_domain = hashlib.sha256(f"{_site_url()}/mcp".encode()).hexdigest()[:32] + ".claudemcpcontent.com"
    return [
        {"uri": CARD_URI, "name": "plan-card", "title": "Base plan card", "mimeType": MCP_APPS_MIME,
         "_meta": {"ui": {"csp": {"resourceDomains": domains, "connectDomains": []}, "domain": claude_domain, "prefersBorder": True}}},
        {"uri": CARD_URI_OPENAI, "name": "plan-card-openai", "title": "Base plan card", "mimeType": "text/html+skybridge",
         "_meta": {"openai/widgetCSP": {"resource_domains": domains, "connect_domains": []}, "openai/widgetPrefersBorder": True,
                   "openai/widgetDescription": "Shows the base plan's preview map, key facts and download links."}},
    ]


def _site_url() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/") or request.host_url.rstrip("/")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _runs_today() -> int:
    from .web import PRIVATE_TOKEN

    if not PRIVATE_TOKEN:
        return _local_counts.get(_today(), 0)
    from .http import session

    n, cursor = 0, None
    while True:
        d = session().get("https://blob.vercel-storage.com", params={"prefix": f"appq/{_today()}/", "limit": 1000, **({"cursor": cursor} if cursor else {})},
                          headers={"authorization": f"Bearer {PRIVATE_TOKEN}", "x-api-version": "7"}, timeout=30).json()
        n += len(d.get("blobs", []))
        cursor = d.get("cursor")
        if not d.get("hasMore"):
            return n


def _count_run() -> None:
    from .web import PRIVATE_TOKEN, private_put

    if not PRIVATE_TOKEN:
        _local_counts[_today()] = _local_counts.get(_today(), 0) + 1
        return
    private_put(f"appq/{_today()}", {"at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def _client() -> str:
    ua = (request.headers.get("User-Agent") or "").lower()
    for key, name in (("openai", "chatgpt"), ("chatgpt", "chatgpt"), ("claude", "claude"), ("anthropic", "claude"), ("cursor", "cursor")):
        if key in ua:
            return name
    return "other"


def _pricing_url() -> str:
    """Plans and pricing for people who run out. An information page (no checkout), as the assistant stores require."""
    try:
        from . import billing

        return f"{_site_url()}/pricing" if billing.live() else _site_url()
    except ImportError:
        return _site_url()


def _subject(meta: dict) -> str:
    """Who to count no-account plans against, hashed: ChatGPT's anonymised per-user id, else the MCP session id we hand
    out on initialize (Claude and others), which is as soft as the browser count on the site. "" if neither."""
    sub = str(meta.get("openai/subject") or "") or ("session:" + request.headers.get("Mcp-Session-Id", "") if request.headers.get("Mcp-Session-Id") else "")
    return hashlib.sha256(sub.encode()).hexdigest()[:32] if sub else ""


def _quota() -> dict | None:
    """Plans left this month for the connected account, for the card; None when signed out or limits are off."""
    from .accounts import current_user
    from .web import FREE_PLANS_PER_MONTH, _is_pro, _month, count_private

    from .oauth import is_reviewer

    u = current_user()
    if not u or is_reviewer(u):
        return None
    if _is_pro():
        return {"pro": True}
    if not FREE_PLANS_PER_MONTH:
        return None
    used = count_private(f"planq/{u['id']}/{_month()}")
    return {"pro": False, "allowance": FREE_PLANS_PER_MONTH, "left": max(0, FREE_PLANS_PER_MONTH - used)}


def _allowance_block(meta: dict) -> dict | None:
    """The same monthly allowance as the site. A connected account uses its own plans (unlimited on Pro); without one,
    ChatGPT's per-user id gets the no-account allowance and then an offer to connect. Assistants that send no user id
    are covered by the daily cap only."""
    from .accounts import current_user
    from .web import ANON_PLANS_PER_MONTH, FREE_PLANS_PER_MONTH, _is_pro, _month, _next_month_label, count_private

    if not FREE_PLANS_PER_MONTH:
        return None
    from .oauth import is_reviewer

    u = current_user()
    if u:
        if is_reviewer(u) or _is_pro() or count_private(f"planq/{u['id']}/{_month()}") < FREE_PLANS_PER_MONTH:
            return None
        return {"isError": True, "content": [{"type": "text", "text": (
            f"This Basesheet account has used this month's {FREE_PLANS_PER_MONTH} free plans; they reset on {_next_month_label()}. "
            f"Plans and pricing: {_pricing_url()}")}]}
    sub = _subject(meta)
    if not (sub and ANON_PLANS_PER_MONTH) or count_private(f"appanon/{sub}/{_month()}") < ANON_PLANS_PER_MONTH:
        return None
    from .oauth import challenge_header

    why = f"Connect a free Basesheet account to keep going: {FREE_PLANS_PER_MONTH} plans a month."
    if not meta.get("openai/subject"):  # Claude and others start sign-in from an HTTP 401, not from a tool result
        return {"http401": why}
    return {"isError": True, "content": [{"type": "text", "text": (
        f"You've made {ANON_PLANS_PER_MONTH} plans this month without a Basesheet account. {why} "
        f"Plans and pricing: {_pricing_url()}")}],
        "_meta": {"mcp/www_authenticate": [challenge_header("insufficient_scope", why)]}}


def _count_success(meta: dict) -> None:
    from .accounts import current_user
    from .web import FREE_PLANS_PER_MONTH, _month, count_plan, private_put

    if not FREE_PLANS_PER_MONTH:
        return
    from .oauth import is_reviewer

    u = current_user()
    if u:
        if not is_reviewer(u):
            count_plan(u["id"])
    elif _subject(meta):
        try:
            private_put(f"appanon/{_subject(meta)}/{_month()}", {"n": 1})
        except Exception as e:  # noqa: BLE001
            print(f"WARN app plan count failed: {e}", flush=True)


def _result_text(rj: dict, link: str) -> str:
    lines = [f"Base plan ready: {rj['title']}", ""]
    for f in rj.get("facts") or []:
        lines.append(f"- {f['label']}: {f['value']}" + (f" ({f['sub']})" if f.get("sub") else ""))
    warn = [x["text"] for x in rj.get("flags") or [] if x.get("level") in ("alert", "caution", "missing")]
    if warn:
        lines += ["", "Needs a look:"] + [f"- {t}" for t in warn[:6]]
    lines += ["", f"Result page with the files (CAD/DXF, SketchUp, Civil 3D LandXML, GIS, PDF; kept 2 days): {link}",
              "", "NOT A SURVEY, NOT A CERTIFIED SITE PLAN, NOT FOR PERMIT SUBMISSION. Parcel lines are assessor tax lines, not "
              "property boundaries, and areas are approximate. Before relying on any line, area, elevation or setback, hire a "
              f"licensed land surveyor ({_site_url()}/guides/when-you-need-a-surveyor), and confirm zoning, flood zones and "
              "wetlands with the jurisdiction."]
    return "\n".join(lines)


def build(args: dict, meta: dict | None = None) -> dict:
    """Run one base plan for a tools/call; returns an MCP CallToolResult."""
    from .geocode import GeocodeError
    from .pipeline import Options, run, zoning_coverage
    from .parcel import jurisdiction_at
    from .web import OUT, looks_like_apn, publish, query_shape, record_usage, save_result

    q = str(args.get("site") or "").strip()[:300]
    if not q:
        return {"isError": True, "content": [{"type": "text", "text": "Give the property's address, parcel number or coordinates."}]}
    if _runs_today() >= DAILY_RUNS:
        return {"isError": True, "content": [{"type": "text", "text": "Basesheet's free daily limit for AI assistants is used up. "
                                              f"Build the plan directly at {_site_url()} instead; it's free."}]}
    blocked = _allowance_block(meta or {})
    if blocked:
        return blocked
    _count_run()
    try:
        buffer_ft = min(1000.0, max(0.0, float(args.get("buffer_ft") or 100)))
    except (TypeError, ValueError):
        buffer_ft = 100.0
    try:
        interval = float(args.get("contour_interval_ft") or 2)
    except (TypeError, ValueError):
        interval = 2.0
    interval = interval if interval in (1.0, 2.0, 5.0) else 2.0
    state = str(args.get("state") or "").strip().upper()[:2] or None
    opts = Options(buffer_ft=buffer_ft, contour_interval=interval, state=state, out_dir=str(OUT), dwg=False, testfit=False)
    run_id = uuid.uuid4().hex[:10]
    base = {"app": _client(), "input": "apn" if looks_like_apn(q) else "address"}
    t0 = time.time()
    try:
        res = run(q, opts, log=lambda m: None)
        urls = publish(run_id, res.out_dir, res.files)
    except Exception as e:  # noqa: BLE001
        geo = isinstance(e, GeocodeError)
        from .web import crash_site

        record_usage({**base, "outcome": "error", "state": state or "", "error_kind": type(e).__name__, "where": crash_site(e),
                      "error": "" if geo else str(e)[:160], "shape": query_shape(q) if geo else None, "seconds": round(time.time() - t0, 1)})
        text = str(e)
        if geo:
            text = text.replace(" Or pick the site on the map below.", "")
            if getattr(e, "suggestions", None):
                text += " Did you mean: " + "; ".join(e.suggestions[:5]) + "?"
            text += " Coordinates ('lat, lon') always work."
        return {"isError": True, "content": [{"type": "text", "text": text}]}
    rj = {"flags": res.flags, "files": urls, "seconds": round(res.timings.get("total", 0)), "state": res.site.state,
          "zoning": res.zoning, "run_id": run_id, "title": res.site.matched_address, "facts": res.facts}
    save_result(run_id, rj)
    record_usage({**base, "outcome": "ok", "state": res.site.state, "parcel": res.site.parcel is not None, "zoning": zoning_coverage(res),
                  "seconds": round(time.time() - t0, 1), "t": {k: round(v, 1) for k, v in res.timings.items()},
                  "failed_layers": sorted(k for k, lr in res.layers.items() if lr.status == "failed"),
                  "jurisdiction": jurisdiction_at(res.site.lon, res.site.lat, timeout=5)})
    _count_success(meta or {})
    link = f"{_site_url()}/r/{run_id}?via=ai"
    content = [{"type": "text", "text": _result_text(rj, link)}]
    thumb = _thumbnail(res.files.get("preview"))
    if thumb:
        content.append({"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(thumb).decode()})
    return {"content": content, "structuredContent": {
        "title": rj["title"], "state": rj["state"], "result_page": link,
        "facts": [{k: f.get(k) for k in ("label", "value", "sub")} for f in rj["facts"] or []],
        "needs_a_look": [x["text"] for x in res.flags if x.get("level") in ("alert", "caution", "missing")],
        "files": {"zip": urls.get("zip"), "pdf": urls.get("pdf"), "preview": urls.get("preview")},
        "disclaimer": "Not a survey. Not for permit submission. Planning-level public data, not a zoning determination. Verify with a licensed surveyor and the jurisdiction.",
        "quota": _quota(), "site": _site_url(),
    }}


def _thumbnail(path: str | None, width: int = 800) -> bytes | None:
    """The preview map as a small JPEG for the chat (the full PNG is ~1 MB)."""
    if not path or not Path(path).exists():
        return None
    try:
        import io

        from PIL import Image

        im = Image.open(path).convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80, optimize=True)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 - the text answer is enough without it
        print(f"WARN preview thumbnail failed: {e}", flush=True)
        return None


def _reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg.update({"error": error} if error else {"result": result})
    return jsonify(msg)


@bp.get("/.well-known/openai-apps-challenge")
def openai_challenge():
    """Domain verification for the ChatGPT app listing: the token from the OpenAI portal, set as OPENAI_APPS_CHALLENGE."""
    tok = os.environ.get("OPENAI_APPS_CHALLENGE", "").strip()
    return Response(tok, mimetype="text/plain") if tok else Response(status=404)


@bp.route("/mcp", methods=["GET", "DELETE"])
def mcp_other():
    return Response("Basesheet MCP server: POST JSON-RPC here (Streamable HTTP, stateless).", status=405,
                    headers={"Allow": "POST"}, mimetype="text/plain")


@bp.post("/mcp")
def mcp_post():
    from .oauth import bearer_user, challenge_header, enabled, use_token_user

    user, refused = bearer_user() if enabled() else (None, "")
    if refused:  # a token was sent but isn't valid: 401 so the assistant refreshes it or reconnects
        return Response('{"error":"invalid_token"}', status=401, mimetype="application/json",
                        headers={"WWW-Authenticate": challenge_header("invalid_token", refused)})
    if user:
        use_token_user(user)
    try:
        msg = request.get_json(force=True)
    except Exception:  # noqa: BLE001
        return _reply(None, error={"code": -32700, "message": "Parse error"}), 400
    if isinstance(msg, list):  # batches aren't part of the current protocol
        return _reply(None, error={"code": -32600, "message": "Batch requests aren't supported"}), 400
    method, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if id_ is None:  # a notification (e.g. notifications/initialized): accept, no body
        return Response(status=202)
    if method == "initialize":
        want = params.get("protocolVersion")
        resp = _reply(id_, {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
                            "serverInfo": {"name": "basesheet", "title": "Basesheet", "version": "1.0.0", "websiteUrl": _site_url()},
                            "instructions": INSTRUCTIONS})
        resp.headers["Mcp-Session-Id"] = uuid.uuid4().hex  # only used to count no-account plans (see _subject)
        return resp
    if method == "ping":
        return _reply(id_, {})
    if method == "tools/list":
        return _reply(id_, {"tools": [_tool()]})
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return _reply(id_, error={"code": -32602, "message": f"Unknown tool: {params.get('name')}"})
        out = build(params.get("arguments") or {}, params.get("_meta") or {})
        if "http401" in out:
            return Response('{"error":"insufficient_scope"}', status=401, mimetype="application/json",
                            headers={"WWW-Authenticate": challenge_header("insufficient_scope", out["http401"])})
        return _reply(id_, out)
    if method == "resources/list":
        return _reply(id_, {"resources": _resources()})
    if method == "resources/read":
        res = next((r for r in _resources() if r["uri"] == params.get("uri")), None)
        if not res:
            return _reply(id_, error={"code": -32002, "message": f"Resource not found: {params.get('uri')}"})
        return _reply(id_, {"contents": [{"uri": res["uri"], "mimeType": res["mimeType"], "text": _card_html(), "_meta": res["_meta"]}]})
    if method == "resources/templates/list":
        return _reply(id_, {"resourceTemplates": []})
    if method == "prompts/list":
        return _reply(id_, {"prompts": []})
    return _reply(id_, error={"code": -32601, "message": f"Method not found: {method}"})

