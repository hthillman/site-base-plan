"""Optional accounts: sign in with an emailed link, save plans, see them later.

No passwords. On the hosted site, Supabase holds the accounts and the `plans`
table: the server asks Supabase Auth for a one-time sign-in token, emails the
link itself through Resend, and verifies the token with Supabase when it's
clicked. The session is a signed Flask cookie. Saved plans copy the run's zip
(and PDF) out of the 2-day `runs/` area into `saved/`, which the cleanup job
never touches. Without Supabase (a local dev server) records are JSON files
and the sign-in link is shown on screen instead of emailed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, redirect, request, session

bp = Blueprint("accounts", __name__)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Basesheet <hello@basesheet.site>")
LOGIN_MAX_AGE_S = 30 * 60
MAX_PLANS = 25  # per free account
PRO_MAX_PLANS = 500
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
LOCAL_DIR = Path(__file__).resolve().parents[2] / "out" / "_accounts"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_SERVICE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SB_ANON = os.environ.get("SUPABASE_ANON_KEY", "")


def supabase_on() -> bool:
    return bool(SUPABASE_URL and SB_SERVICE)


def _sb(service: bool = True, **extra) -> dict:
    key = SB_SERVICE if service or not SB_ANON else SB_ANON
    return {"apikey": key, "authorization": f"Bearer {key}", **extra}


def sb_sign_in_token(email: str) -> tuple[str, str]:
    """One-time sign-in token from Supabase Auth (creates the account on first use). No email is sent by Supabase."""
    from .http import session as http

    r = http().post(f"{SUPABASE_URL}/auth/v1/admin/generate_link", json={"type": "magiclink", "email": email}, headers=_sb(), timeout=20)
    if r.status_code >= 400 and "not found" in r.text.lower():
        http().post(f"{SUPABASE_URL}/auth/v1/admin/users", json={"email": email, "email_confirm": True}, headers=_sb(), timeout=20).raise_for_status()
        r = http().post(f"{SUPABASE_URL}/auth/v1/admin/generate_link", json={"type": "magiclink", "email": email}, headers=_sb(), timeout=20)
    r.raise_for_status()
    d = r.json()
    props = d.get("properties") or d
    return props["hashed_token"], props.get("verification_type") or "magiclink"


def sb_verify(token_hash: str, vtype: str) -> dict:
    """Exchange a clicked token for the Supabase user ({id, email}). Raises on an expired or used token."""
    from .http import session as http

    r = http().post(f"{SUPABASE_URL}/auth/v1/verify", json={"type": vtype, "token_hash": token_hash}, headers=_sb(service=False), timeout=20)
    if r.status_code >= 400 and vtype != "email":
        r = http().post(f"{SUPABASE_URL}/auth/v1/verify", json={"type": "email", "token_hash": token_hash}, headers=_sb(service=False), timeout=20)
    r.raise_for_status()
    u = r.json().get("user") or {}
    return {"id": u["id"], "email": u.get("email", "")}


def _rest(method: str, query: str, **kw):
    from .http import session as http

    r = http().request(method, f"{SUPABASE_URL}/rest/v1/plans{query}", headers=_sb(Prefer="return=representation"), timeout=20, **kw)
    r.raise_for_status()
    return r.json() if r.text else []


def _blob_token() -> str:
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def _private_token() -> str:
    return os.environ.get("PRIVATE_READ_WRITE_TOKEN", "")


def local_dev() -> bool:
    return not _blob_token()


def enabled() -> bool:
    """Accounts work at all (sessions can be signed, and there's somewhere to keep plans)."""
    return (bool(SECRET_KEY) and supabase_on()) or local_dev()


def can_sign_up() -> bool:
    """New sign-ins are possible: switched on (ACCOUNTS_LIVE=1) with email set up, or a dev server."""
    if local_dev():
        return True
    return enabled() and bool(RESEND_API_KEY) and os.environ.get("ACCOUNTS_LIVE") == "1"


def current_user() -> dict | None:
    try:
        uid, email = session.get("uid"), session.get("email")
    except RuntimeError:
        return None
    return {"id": uid, "email": email} if uid and email else None


def current_email() -> str | None:
    try:
        return session.get("email") if session.get("uid") else None
    except RuntimeError:  # outside a request
        return None


def _uid(email: str) -> str:
    key = (SECRET_KEY or "dev").encode()
    return hmac.new(key, email.strip().lower().encode(), hashlib.sha256).hexdigest()[:20]


def _serializer():
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(SECRET_KEY or "dev-only-secret", salt="basesheet-login")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ storage
def _priv_headers() -> dict:
    return {"authorization": f"Bearer {_private_token()}", "x-api-version": "7"}


def _priv_put(path: str, record: dict) -> None:
    if local_dev() or not _private_token():
        f = LOCAL_DIR / f"{path}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(record, indent=2))
        return
    from .http import session as http

    r = http().put(f"https://blob.vercel-storage.com/{path}.json", data=json.dumps(record).encode(),
                   headers={**_priv_headers(), "x-content-type": "application/json", "x-add-random-suffix": "0",
                            "x-allow-overwrite": "1", "x-vercel-blob-access": "private"}, timeout=30)
    r.raise_for_status()


def _priv_list(prefix: str) -> list[dict]:
    """[{record, ref}] under a prefix; ref deletes it."""
    if local_dev() or not _private_token():
        folder, stem = (LOCAL_DIR / prefix, "") if prefix.endswith("/") else ((LOCAL_DIR / prefix).parent, Path(prefix).name)
        return [{"record": json.loads(p.read_text()), "ref": str(p)} for p in sorted(folder.glob(stem + "*.json"))] if folder.exists() else []
    from .http import session as http

    out, cursor = [], None
    while True:
        d = http().get("https://blob.vercel-storage.com", params={"prefix": prefix, "limit": 1000, **({"cursor": cursor} if cursor else {})},
                       headers=_priv_headers(), timeout=30).json()
        for b in d.get("blobs", []):
            rec = http().get(b["url"], headers={"authorization": f"Bearer {_private_token()}"}, timeout=30).json()
            out.append({"record": rec, "ref": b["url"]})
        cursor = d.get("cursor")
        if not d.get("hasMore"):
            return out


def _priv_delete(refs: list[str]) -> None:
    if not refs:
        return
    if local_dev() or not _private_token():
        for r in refs:
            Path(r).unlink(missing_ok=True)
        return
    from .http import session as http

    http().post("https://blob.vercel-storage.com/delete", json={"urls": refs}, headers=_priv_headers(), timeout=30).raise_for_status()


def _public_delete(urls: list[str]) -> None:
    urls = [u for u in urls if u and u.startswith("https://")]
    if not urls or not _blob_token():
        return
    from .http import session as http

    http().post("https://blob.vercel-storage.com/delete", json={"urls": urls},
                headers={"authorization": f"Bearer {_blob_token()}", "x-api-version": "7"}, timeout=30).raise_for_status()


# ------------------------------------------------------------------ email
def _send_link(email: str, link: str) -> None:
    from .http import session as http

    text = (f"Here's your link to sign in to Basesheet:\n\n{link}\n\n"
            "It works for 30 minutes. If you didn't ask for this, you can ignore this email.\n")
    html = (f'<p>Here\'s your link to sign in to Basesheet:</p><p><a href="{link}">Sign in to Basesheet</a></p>'
            "<p>It works for 30 minutes. If you didn't ask for this, you can ignore this email.</p>")
    r = http().post("https://api.resend.com/emails", json={"from": EMAIL_FROM, "to": [email], "subject": "Your Basesheet sign-in link",
                                                           "text": text, "html": html},
                    headers={"authorization": f"Bearer {RESEND_API_KEY}"}, timeout=20)
    r.raise_for_status()


# ------------------------------------------------------------------ saving
def _valid_run_url(url: str, run_id: str) -> bool:
    if local_dev():
        return url.startswith((f"/zip/{run_id}", f"/files/{run_id}/"))
    u = urlparse(url)
    return (u.scheme == "https" and u.netloc.endswith(".public.blob.vercel-storage.com")
            and u.path.startswith("/runs/") and run_id in u.path)


def save_plan(user: dict, plan: dict) -> dict:
    """Copy a run's files out of the 2-day area and record the plan. `plan` comes from the client:
    {run_id, title, files: {zip, pdf?}, state}."""
    run_id = str(plan.get("run_id") or "")
    files = plan.get("files") or {}
    if not re.fullmatch(r"[0-9a-f]{10}", run_id) or not files.get("zip"):
        raise ValueError("That plan can't be saved (missing run details).")
    for k in ("zip", "pdf"):
        if files.get(k) and not _valid_run_url(files[k], run_id):
            raise ValueError("That plan can't be saved (unexpected file location).")
    uid = user["id"]
    if supabase_on():
        found = _rest("GET", f"?user_id=eq.{uid}&run_id=eq.{run_id}&select=*")
        if found:
            return _shape(found[0])
    else:
        for existing in _priv_list(f"plans/{uid}/"):
            if existing["record"].get("run_id") == run_id:
                return existing["record"]
    have = len(_rest("GET", f"?user_id=eq.{uid}&select=id")) if supabase_on() else len(_priv_list(f"plans/{uid}/"))
    cap = PRO_MAX_PLANS if _is_pro(user) else MAX_PLANS
    if have >= cap:
        if cap == PRO_MAX_PLANS:
            raise ValueError(f"You've saved {cap} plans. Delete one in My plans to save this one.")
        raise ValueError(f"You've saved {MAX_PLANS} plans, the most a free account keeps. Delete one in My plans to save this, "
                         "or if you're using Basesheet at a firm and need more, tell us on the For firms page (basesheet.site/firms).")
    plan_id = uuid.uuid4().hex[:12]
    kept = {}
    if local_dev():
        kept = {k: files[k] for k in ("zip", "pdf") if files.get(k)}
    else:
        from .http import session as http

        folder = f"saved/{uid}-{secrets.token_hex(8)}"
        for k in ("zip", "pdf"):
            if not files.get(k):
                continue
            r = http().get(files[k], timeout=120)
            if r.status_code == 404:
                raise ValueError("This plan's files have already expired (runs are kept for 2 days). Build it again, then save.")
            r.raise_for_status()
            name = Path(urlparse(files[k]).path).name
            put = http().put(f"https://blob.vercel-storage.com/{folder}/{name}", data=r.content,
                             headers={"authorization": f"Bearer {_blob_token()}", "x-api-version": "7",
                                      "x-content-type": "application/zip" if k == "zip" else "application/pdf",
                                      "x-add-random-suffix": "0", "x-allow-overwrite": "1"}, timeout=120)
            put.raise_for_status()
            kept[k] = put.json()["url"]
    title = str(plan.get("title") or "Site plan")[:200]
    state = str(plan.get("state") or "")[:2]
    if supabase_on():
        row = _rest("POST", "", json={"user_id": uid, "run_id": run_id, "title": title, "state": state, "files": kept})
        return _shape(row[0])
    rec = {"id": plan_id, "run_id": run_id, "title": title, "state": state, "files": kept, "saved_at": _now()}
    _priv_put(f"plans/{uid}/{plan_id}", rec)
    return rec


def _is_pro(user: dict) -> bool:
    try:
        from .billing import is_pro, live
    except ImportError:
        return False
    return live() and is_pro(user)


def _shape(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "run_id", "title", "state", "files", "saved_at")}


def list_plans(user: dict) -> list[dict]:
    if supabase_on():
        return [_shape(r) for r in _rest("GET", f"?user_id=eq.{user['id']}&select=*&order=saved_at.desc")]
    recs = [x["record"] for x in _priv_list(f"plans/{user['id']}/")]
    return sorted(recs, key=lambda r: r.get("saved_at", ""), reverse=True)


def delete_plan(user: dict, plan_id: str) -> bool:
    if supabase_on():
        if not re.fullmatch(r"[0-9a-f-]{36}", plan_id):
            return False
        gone = _rest("DELETE", f"?id=eq.{plan_id}&user_id=eq.{user['id']}")
        for row in gone:
            _public_delete(list((row.get("files") or {}).values()))
        return bool(gone)
    for x in _priv_list(f"plans/{user['id']}/"):
        if x["record"].get("id") == plan_id:
            _public_delete(list((x["record"].get("files") or {}).values()))
            _priv_delete([x["ref"]])
            return True
    return False


# ------------------------------------------------------------------ routes
@bp.post("/api/auth/start")
def auth_start():
    if not can_sign_up():
        abort(404)
    d = request.get_json(force=True, silent=True) or {}
    if d.get("website"):
        return jsonify(ok=True)
    email = str(d.get("email") or "").strip()[:254]
    if not EMAIL_RE.match(email):
        return jsonify(error="That doesn't look like an email address."), 400
    payload = {"e": email.lower()}
    pending = d.get("save")
    if isinstance(pending, dict):
        payload["s"] = {k: pending.get(k) for k in ("run_id", "title", "files", "state")}
    if supabase_on():
        try:
            th, vt = sb_sign_in_token(email.lower())
        except Exception as e:  # noqa: BLE001
            print(f"WARN supabase sign-in token failed: {e}", flush=True)
            return jsonify(error="Sign-in isn't working right now. Try again in a minute."), 502
        payload.update(th=th, vt=vt)
    token = _serializer().dumps(payload)
    base = os.environ.get("SITE_URL", "").rstrip("/") or request.host_url.rstrip("/")
    link = f"{base}/auth?t={token}"
    if RESEND_API_KEY and not local_dev():
        try:
            _send_link(email, link)
        except Exception as e:  # noqa: BLE001
            print(f"WARN sign-in email failed: {e}", flush=True)
            return jsonify(error="Couldn't send the email just now. Try again in a minute."), 502
        return jsonify(ok=True)
    print(f"Sign-in link for {email}: {link}", flush=True)
    return jsonify(ok=True, dev_link=link)


@bp.get("/auth")
def auth_finish():
    from itsdangerous import BadSignature, SignatureExpired

    if not enabled():
        abort(404)
    try:
        payload = _serializer().loads(request.args.get("t", ""), max_age=LOGIN_MAX_AGE_S)
    except SignatureExpired:
        return redirect("/plans?link=expired")
    except BadSignature:
        return redirect("/plans?link=bad")
    if supabase_on():
        try:
            user = sb_verify(payload["th"], payload.get("vt", "magiclink"))
        except Exception as e:  # noqa: BLE001 - used or expired on Supabase's side
            print(f"WARN supabase verify failed: {e}", flush=True)
            return redirect("/plans?link=expired")
    else:
        user = {"id": _uid(payload["e"]), "email": payload["e"]}
    session.permanent = True
    session["uid"], session["email"] = user["id"], user["email"] or payload["e"]
    if payload.get("s"):
        try:
            save_plan(user, payload["s"])
            return redirect("/plans?saved=1")
        except Exception as e:  # noqa: BLE001
            print(f"WARN save after sign-in failed: {e}", flush=True)
            return redirect("/plans?saved=0")
    return redirect("/plans")


@bp.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/me")
def me():
    u = current_user()
    return jsonify(email=u["email"] if u else None, can_sign_up=can_sign_up(), quota=_quota(u))


def _quota(u: dict | None) -> dict | None:
    """This month's free-plan allowance for the page's "X of N left" line; None when limits are off or for Pro."""
    from . import web

    if not web.FREE_PLANS_PER_MONTH or web._is_pro():
        return None
    q = {"allowance": web.FREE_PLANS_PER_MONTH, "anon_allowance": web.ANON_PLANS_PER_MONTH}
    if u:
        q["used"] = web.count_private(f"planq/{u['id']}/{web._month()}")
    return q


@bp.get("/api/plans")
def plans_list():
    u = current_user()
    if not u:
        return jsonify(error="Sign in to see your plans."), 401
    return jsonify(plans=list_plans(u))


@bp.post("/api/plans")
def plans_save():
    u = current_user()
    if not u:
        return jsonify(error="Sign in to save plans."), 401
    try:
        return jsonify(plan=save_plan(u, request.get_json(force=True, silent=True) or {}))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@bp.delete("/api/plans/<plan_id>")
def plans_delete(plan_id):
    u = current_user()
    if not u:
        return jsonify(error="Sign in first."), 401
    return jsonify(ok=delete_plan(u, plan_id))
