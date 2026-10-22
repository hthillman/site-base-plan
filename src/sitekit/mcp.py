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
    "Basesheet builds a planning-level site base plan for a US property: parcel lines, LiDAR contours, slope, soils, "
    "FEMA flood zones, wetlands, roads, building outlines and zoning where covered. Call build_base_plan with the "
    "property's address, parcel number or coordinates. Share the result page link with the user: that's where they "
    "download the CAD (DXF), SketchUp, Civil 3D (LandXML), GIS and PDF files. Everything is unverified public data, "
    "not a survey or zoning determination; say so when presenting it."
)

TOOL = {
    "name": "build_base_plan",
    "title": "Build a site base plan",
    "description": (
        "Build a planning-level base plan for one US property from public data and return its key facts (parcel size, "
        "flood zone, wetlands, elevation and slope, soils, buildings, zoning where covered), a preview map, and a link to "
        "the result page where the CAD, SketchUp, GIS and PDF files are downloaded (kept 2 days). Takes about 15-60 "
        "seconds. The address is the property being studied, not the user's location. Outputs are unverified and must be "
        "checked by a licensed surveyor and the jurisdiction before anyone relies on them."
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
    "_meta": {"openai/toolInvocation/invoking": "Building the base plan…", "openai/toolInvocation/invoked": "Base plan ready"},
}


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


def _result_text(rj: dict, link: str) -> str:
    lines = [f"Base plan ready: {rj['title']}", ""]
    for f in rj.get("facts") or []:
        lines.append(f"- {f['label']}: {f['value']}" + (f" ({f['sub']})" if f.get("sub") else ""))
    warn = [x["text"] for x in rj.get("flags") or [] if x.get("level") in ("alert", "caution", "missing")]
    if warn:
        lines += ["", "Needs a look:"] + [f"- {t}" for t in warn[:6]]
    lines += ["", f"Result page with the files (CAD/DXF, SketchUp, Civil 3D LandXML, GIS, PDF; kept 2 days): {link}",
              "", "NOT A SURVEY. NOT FOR PERMIT SUBMISSION. Planning-level public data, not a zoning determination: verify with a licensed surveyor and the "
              "jurisdiction before relying on it."]
    return "\n".join(lines)


def build(args: dict) -> dict:
    """Run one base plan for a tools/call; returns an MCP CallToolResult."""
    from .geocode import GeocodeError
    from .pipeline import Options, run, zoning_coverage
    from .web import OUT, looks_like_apn, publish, query_shape, record_usage, save_result

    q = str(args.get("site") or "").strip()[:300]
    if not q:
        return {"isError": True, "content": [{"type": "text", "text": "Give the property's address, parcel number or coordinates."}]}
    if _runs_today() >= DAILY_RUNS:
        return {"isError": True, "content": [{"type": "text", "text": "Basesheet's free daily limit for AI assistants is used up. "
                                              f"Build the plan directly at {_site_url()} instead; it's free."}]}
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
                  "seconds": round(time.time() - t0, 1),
                  "failed_layers": sorted(k for k, lr in res.layers.items() if lr.status == "failed")})
    link = f"{_site_url()}/r/{run_id}"
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


@bp.route("/mcp", methods=["GET", "DELETE"])
def mcp_other():
    return Response("Basesheet MCP server: POST JSON-RPC here (Streamable HTTP, stateless).", status=405,
                    headers={"Allow": "POST"}, mimetype="text/plain")


@bp.post("/mcp")
def mcp_post():
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
        return _reply(id_, {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {"name": "basesheet", "title": "Basesheet", "version": "1.0.0", "websiteUrl": _site_url()},
                            "instructions": INSTRUCTIONS})
    if method == "ping":
        return _reply(id_, {})
    if method == "tools/list":
        return _reply(id_, {"tools": [TOOL]})
    if method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return _reply(id_, error={"code": -32602, "message": f"Unknown tool: {params.get('name')}"})
        return _reply(id_, build(params.get("arguments") or {}))
    if method in ("resources/list", "prompts/list"):
        return _reply(id_, {method.split("/")[0]: []})
    return _reply(id_, error={"code": -32601, "message": f"Method not found: {method}"})

