"""OAuth 2.1 for the MCP server, so ChatGPT and Claude users can connect their Basesheet account.

Basesheet is its own authorization server, built on the emailed-link sign-in (accounts.py): /oauth/authorize signs
the person in if needed, asks once to connect, and hands the assistant a code; /oauth/token swaps it (with PKCE) for
an access token the MCP server checks on each call. Signed in, assistant runs count toward that account's monthly
plans (unlimited on Pro). Without a token the tool still works anonymously.

Nothing is stored: clients, codes and tokens are signed with SECRET_KEY (itsdangerous), so they can't be listed or
revoked one by one. Rotating SECRET_KEY disconnects every assistant (and signs everyone out of the site).

Clients register either way the assistants do it:
- Dynamic Client Registration (RFC 7591): /oauth/register returns a client_id that carries its redirect URIs, signed.
- Client ID Metadata Documents: the client_id is an https URL on a known assistant host (ALLOWED_CIMD_HOSTS),
  fetched once and cached, whose redirect_uris must list the redirect.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode, urlparse

from flask import Blueprint, abort, g, jsonify, redirect, request
from markupsafe import escape

from . import accounts as A

bp = Blueprint("oauth", __name__)

SCOPE = "plans"
ACCESS_TTL_S = 24 * 3600
REFRESH_TTL_S = 180 * 86400
CODE_TTL_S = 300
ALLOWED_CIMD_HOSTS = {"chatgpt.com", "claude.ai", "claude.com", "anthropic.com"}
_cimd_cache: dict[str, tuple[float, dict]] = {}


def site() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/") or request.host_url.rstrip("/")


def resource() -> str:
    return f"{site()}/mcp"


def enabled() -> bool:
    """Sign-in must work for anyone to connect an account."""
    return A.can_sign_up()


def _ser(salt: str):
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(A.SECRET_KEY or "dev-only-secret", salt=f"basesheet-oauth-{salt}")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ------------------------------------------------------------------ discovery
def protected_resource_metadata() -> dict:
    return {"resource": resource(), "authorization_servers": [site()], "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"], "resource_name": "Basesheet",
            "resource_documentation": f"{site()}/guides/use-in-chatgpt-and-claude"}


@bp.get("/.well-known/oauth-protected-resource")
@bp.get("/.well-known/oauth-protected-resource/mcp")
def prm():
    if not enabled():
        abort(404)
    return jsonify(protected_resource_metadata())


@bp.get("/.well-known/oauth-authorization-server")
@bp.get("/.well-known/oauth-authorization-server/mcp")
@bp.get("/.well-known/openid-configuration")
def asm():
    if not enabled():
        abort(404)
    s = site()
    return jsonify({
        "issuer": s, "authorization_endpoint": f"{s}/oauth/authorize", "token_endpoint": f"{s}/oauth/token",
        "registration_endpoint": f"{s}/oauth/register", "scopes_supported": [SCOPE], "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"], "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True, "service_documentation": f"{s}/guides/use-in-chatgpt-and-claude",
    })


def challenge_header(error: str = "", description: str = "") -> str:
    """WWW-Authenticate value pointing the assistant at our metadata (and why, when a token was refused)."""
    parts = [f'resource_metadata="{site()}/.well-known/oauth-protected-resource"', f'scope="{SCOPE}"']
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append(f'error_description="{description}"')
    return "Bearer " + ", ".join(parts)


# ------------------------------------------------------------------ clients
def _redirect_ok(uri: str) -> bool:
    u = urlparse(uri)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))


@bp.post("/oauth/register")
def register():
    if not enabled():
        abort(404)
    d = request.get_json(force=True, silent=True) or {}
    uris = [str(u) for u in (d.get("redirect_uris") or []) if isinstance(u, str)][:10]
    if not uris or not all(_redirect_ok(u) and len(u) < 500 for u in uris):
        return jsonify(error="invalid_redirect_uri", error_description="Redirect URIs must be https (or http on localhost)."), 400
    name = str(d.get("client_name") or "")[:80]
    cid = "dcr." + _ser("client").dumps({"r": uris, "n": name})
    return jsonify(client_id=cid, client_id_issued_at=int(time.time()), redirect_uris=uris, client_name=name,
                   token_endpoint_auth_method="none", grant_types=["authorization_code", "refresh_token"],
                   response_types=["code"]), 201


def client_info(cid: str) -> dict | None:
    """{name, redirect_uris} for a registered or metadata-document client, or None if it isn't one we accept."""
    if cid.startswith("dcr."):
        try:
            c = _ser("client").loads(cid[4:])
        except Exception:  # noqa: BLE001
            return None
        return {"name": c.get("n") or "", "redirect_uris": c.get("r") or []}
    u = urlparse(cid)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in ALLOWED_CIMD_HOSTS):
        return None
    hit = _cimd_cache.get(cid)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        from .http import session

        doc = session().get(cid, timeout=8, allow_redirects=False).json()
    except Exception as e:  # noqa: BLE001
        print(f"WARN client metadata fetch failed: {e}", flush=True)
        return None
    if doc.get("client_id") != cid:
        return None
    info = {"name": str(doc.get("client_name") or host)[:80], "redirect_uris": [str(x) for x in doc.get("redirect_uris") or []]}
    _cimd_cache[cid] = (time.time() + 3600, info)
    return info


def _client_label(info: dict, redirect_uri: str) -> str:
    """What the consent page calls the assistant: its registered name, else recognised from where it sends the code."""
    host = (urlparse(redirect_uri).hostname or "").lower()
    for key, label in (("chatgpt.com", "ChatGPT"), ("openai.com", "ChatGPT"), ("claude.ai", "Claude"), ("claude.com", "Claude"), ("anthropic.com", "Claude")):
        if host == key or host.endswith("." + key):
            return label
    return info.get("name") or host or "An app"


# ------------------------------------------------------------------ app-review sign-in
# App reviewers (OpenAI, Anthropic) need an email and password; Basesheet otherwise only signs in by emailed link.
# One reviewer account, set as REVIEWER_LOGIN="email|pbkdf2_sha256$iterations$salt_hex$hash_hex" (the password itself is
# never stored). It never hits a monthly limit, so a review can't fail on the allowance.
REVIEWER_PREFIX = "reviewer-"


def _reviewer() -> tuple[str, str] | None:
    raw = os.environ.get("REVIEWER_LOGIN", "")
    if "|" not in raw:
        return None
    email, h = raw.split("|", 1)
    return email.strip().lower(), h.strip()


def reviewer_password_ok(email: str, password: str) -> bool:
    r = _reviewer()
    if not r or email.strip().lower() != r[0]:
        return False
    try:
        algo, iters, salt, want = r[1].split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
    except Exception:  # noqa: BLE001
        return False
    return algo == "pbkdf2_sha256" and hmac.compare_digest(got, want)


def is_reviewer(user: dict | None) -> bool:
    return bool(user and str(user.get("id", "")).startswith(REVIEWER_PREFIX))


@bp.post("/oauth/reviewer-sign-in")
def reviewer_sign_in():
    from flask import session

    nxt = request.form.get("next", "")
    if not nxt.startswith("/oauth/authorize?"):
        abort(400)
    email, pw = request.form.get("email", ""), request.form.get("password", "")
    if not (enabled() and reviewer_password_ok(email, pw)):
        time.sleep(1)
        return redirect(nxt + "&review_login=failed", code=303)
    session.permanent = True
    session["uid"] = REVIEWER_PREFIX + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    session["email"] = email.strip().lower()
    return redirect(nxt, code=303)


# ------------------------------------------------------------------ authorize
AUTH_PARAMS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope", "resource")


def _check_request(p: dict) -> tuple[dict | None, str]:
    """(client info, "") if the authorization request is valid, else (None, why)."""
    info = client_info(p.get("client_id", ""))
    if not info:
        return None, "This app isn't registered with Basesheet."
    if p.get("redirect_uri") not in info["redirect_uris"]:
        return None, "The app's return address doesn't match its registration."
    if p.get("response_type") != "code" or p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
        return None, "The app sent an incomplete sign-in request (it needs PKCE with S256)."
    return info, ""


def _back(p: dict, **params) -> str:
    q = {**params, "iss": site()}
    if p.get("state"):
        q["state"] = p["state"]
    return p["redirect_uri"] + ("&" if "?" in p["redirect_uri"] else "?") + urlencode(q)


def _page(title: str, body: str, status: int = 200):
    from .pages import layout

    return layout(title, "/plans", body, description="Connect an AI assistant to your Basesheet account."), status, {
        "Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


def _consent_token(uid: str, p: dict) -> str:
    return _ser("consent").dumps({"u": uid, "h": hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()})


@bp.route("/oauth/authorize", methods=["GET", "POST"])
def authorize():
    if not enabled():
        abort(404)
    src = request.form if request.method == "POST" else request.args
    p = {k: src.get(k, "") for k in AUTH_PARAMS if src.get(k)}
    info, why = _check_request(p)
    if not info:  # never redirect to an address we couldn't verify
        return _page("Can't connect", f"<h1>Can't connect</h1><p>{escape(why)}</p>", 400)
    who = _client_label(info, p["redirect_uri"])
    user = A.current_user()
    if request.method == "POST":
        if src.get("decision") != "allow":
            return redirect(_back(p, error="access_denied", error_description="The person declined to connect."), code=303)
        try:
            ok = user and _ser("consent").loads(src.get("csrf", ""), max_age=1800) == {
                "u": user["id"], "h": hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()}
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            return _page("Can't connect", "<h1>That didn't work</h1><p>The page expired. Go back to the app and connect again.</p>", 400)
        code = _ser("code").dumps({"u": user["id"], "e": user["email"], "c": p["client_id"], "r": p["redirect_uri"],
                                   "x": p["code_challenge"], "a": p.get("resource") or resource()})
        return redirect(_back(p, code=code), code=303)
    here = "/oauth/authorize?" + urlencode(p)
    if not user:
        body = (f"<h1>Connect {escape(who)} to Basesheet</h1>"
                f"<p>{escape(who)} wants to build base plans with your Basesheet account. Sign in to continue: we'll email "
                "you a link, no password.</p>"
                '<form class="savef" id="oasignin"><input type="email" name="email" required maxlength="254" placeholder="Your email" '
                'aria-label="Email"><input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">'
                '<button>Email me a sign-in link</button></form><p class="fine" id="oamsg"></p>'
                "<p class=\"fine\">Open the link on this device; it brings you back here to finish.</p>")
        if _reviewer():
            failed = '<p class="fine err">That email and password didn\'t match.</p>' if request.args.get("review_login") else ""
            body += ('<details><summary class="fine">Reviewing this app? Sign in with the test account</summary>'
                     f'<form method="post" action="/oauth/reviewer-sign-in" class="savef"><input type="hidden" name="next" value="{escape(here)}">'
                     '<input type="email" name="email" required placeholder="Test account email" aria-label="Test account email">'
                     '<input type="password" name="password" required placeholder="Password" aria-label="Password">'
                     f'<button>Sign in</button></form>{failed}</details>')
        script = ("<script>const f=document.getElementById('oasignin'),m=document.getElementById('oamsg');"
                  "f.onsubmit=async e=>{e.preventDefault();f.querySelector('button').disabled=true;"
                  "const r=await fetch('/api/auth/start',{method:'POST',headers:{'Content-Type':'application/json'},"
                  f"body:JSON.stringify({{email:f.email.value,website:f.website.value,next:{json.dumps(here)}}})}});"
                  "const k=await r.json().catch(()=>({}));if(r.ok){f.hidden=true;m.className='fine ok';"
                  "m.innerHTML='Check your email for the sign-in link (good for 30 minutes).'+(k.dev_link?' <a href=\"'+k.dev_link+'\">Dev: open link</a>':'')}"
                  "else{f.querySelector('button').disabled=false;m.className='fine err';m.textContent=k.error||'Something went wrong.'}}</script>")
        from .pages import layout

        return layout(f"Connect {who} · Basesheet", "/plans", body, script, description="Connect an AI assistant to your Basesheet account."), 200, {
            "Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}
    hidden = "".join(f'<input type="hidden" name="{k}" value="{escape(v)}">' for k, v in p.items())
    body = (f"<h1>Connect {escape(who)} to Basesheet?</h1>"
            f"<p>Signed in as <b>{escape(user['email'])}</b>.</p>"
            f"<p>{escape(who)} will be able to build base plans with your account. They count toward your monthly plans "
            "(unlimited with Pro). It can't see, change or delete your saved plans.</p>"
            f'<form method="post" action="/oauth/authorize">{hidden}'
            f'<input type="hidden" name="csrf" value="{escape(_consent_token(user["id"], p))}">'
            '<button name="decision" value="allow" autofocus>Connect</button> '
            '<button name="decision" value="deny" class="linkbtn">Cancel</button></form>'
            '<p class="fine">Not you? <a href="/plans">Sign out on My plans</a>, then connect again.</p>')
    return _page(f"Connect {who} · Basesheet", body)


# ------------------------------------------------------------------ token
def _token_error(error: str, description: str, status: int = 400):
    return jsonify(error=error, error_description=description), status, {"Cache-Control": "no-store"}


def _issue(uid: str, email: str, cid: str, aud: str) -> dict:
    access = _ser("access").dumps({"u": uid, "e": email, "a": aud, "s": SCOPE})
    refresh = _ser("refresh").dumps({"u": uid, "e": email, "c": cid, "a": aud})
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL_S, "refresh_token": refresh, "scope": SCOPE}


@bp.post("/oauth/token")
def token():
    if not enabled():
        abort(404)
    f = request.form
    grant, cid = f.get("grant_type", ""), f.get("client_id", "")
    if grant == "authorization_code":
        try:
            c = _ser("code").loads(f.get("code", ""), max_age=CODE_TTL_S)
        except Exception:  # noqa: BLE001
            return _token_error("invalid_grant", "The code is expired or invalid.")
        if c["c"] != cid or c["r"] != f.get("redirect_uri", ""):
            return _token_error("invalid_grant", "The code was issued to a different client or redirect.")
        verifier = f.get("code_verifier", "")
        if not (43 <= len(verifier) <= 128) or not hmac.compare_digest(_b64(hashlib.sha256(verifier.encode()).digest()), c["x"]):
            return _token_error("invalid_grant", "PKCE verification failed.")
        return jsonify(_issue(c["u"], c["e"], cid, f.get("resource") or c["a"])), 200, {"Cache-Control": "no-store"}
    if grant == "refresh_token":
        try:
            r = _ser("refresh").loads(f.get("refresh_token", ""), max_age=REFRESH_TTL_S)
        except Exception:  # noqa: BLE001
            return _token_error("invalid_grant", "The refresh token is expired or invalid.")
        if cid and r["c"] != cid:
            return _token_error("invalid_grant", "The refresh token was issued to a different client.")
        return jsonify(_issue(r["u"], r["e"], r["c"], r["a"])), 200, {"Cache-Control": "no-store"}
    return _token_error("unsupported_grant_type", "Use authorization_code or refresh_token.")


# ------------------------------------------------------------------ checking tokens (used by mcp.py)
def bearer_user() -> tuple[dict | None, str]:
    """(user, "") for a valid access token, (None, "") when there is none, (None, why) when one was sent but refused."""
    h = request.headers.get("Authorization", "")
    if not h.lower().startswith("bearer "):
        return None, ""
    try:
        t = _ser("access").loads(h[7:].strip(), max_age=ACCESS_TTL_S)
    except Exception:  # noqa: BLE001
        return None, "The access token is expired or invalid."
    if t.get("a") not in (resource(), site(), site() + "/"):
        return None, "The access token is for a different server."
    return {"id": t["u"], "email": t["e"]}, ""


def use_token_user(user: dict) -> None:
    """Make accounts.current_user() return the token's user for the rest of this request."""
    g.oauth_user = user
