"""Optional accounts: sign in with an emailed link, save plans, see them later.

No passwords. A sign-in link is a signed, 30-minute token; the session is a
signed cookie. Saved plans copy the run's zip (and PDF) out of the 2-day
`runs/` area into `saved/`, which the cleanup job never touches, and keep a
small private record per plan. Everything is off unless SECRET_KEY is set, and
the save button only shows where email can actually be sent (RESEND_API_KEY),
or on a local dev server, where the link is shown on screen instead.
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
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
LOCAL_DIR = Path(__file__).resolve().parents[2] / "out" / "_accounts"


def _blob_token() -> str:
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def _private_token() -> str:
    return os.environ.get("PRIVATE_READ_WRITE_TOKEN", "")


def local_dev() -> bool:
    return not _blob_token()


def enabled() -> bool:
    """Accounts work at all (sessions can be signed)."""
    return bool(SECRET_KEY) or local_dev()


def can_sign_up() -> bool:
    """New sign-ins are possible: email can be sent, or we're on a dev server."""
    return enabled() and (bool(RESEND_API_KEY) or local_dev())


def current_email() -> str | None:
    try:
        return session.get("email")
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


def save_plan(email: str, plan: dict) -> dict:
    """Copy a run's files out of the 2-day area and record the plan. `plan` comes from the client:
    {run_id, title, files: {zip, pdf?}, state}."""
    run_id = str(plan.get("run_id") or "")
    files = plan.get("files") or {}
    if not re.fullmatch(r"[0-9a-f]{10}", run_id) or not files.get("zip"):
        raise ValueError("That plan can't be saved (missing run details).")
    for k in ("zip", "pdf"):
        if files.get(k) and not _valid_run_url(files[k], run_id):
            raise ValueError("That plan can't be saved (unexpected file location).")
    uid = _uid(email)
    for existing in _priv_list(f"plans/{uid}/"):
        if existing["record"].get("run_id") == run_id:
            return existing["record"]
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
    rec = {"id": plan_id, "run_id": run_id, "title": str(plan.get("title") or "Site plan")[:200],
           "state": str(plan.get("state") or "")[:2], "files": kept, "saved_at": _now()}
    _priv_put(f"plans/{uid}/{plan_id}", rec)
    return rec


def list_plans(email: str) -> list[dict]:
    recs = [x["record"] for x in _priv_list(f"plans/{_uid(email)}/")]
    return sorted(recs, key=lambda r: r.get("saved_at", ""), reverse=True)


def delete_plan(email: str, plan_id: str) -> bool:
    for x in _priv_list(f"plans/{_uid(email)}/"):
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
    email = payload["e"]
    session.permanent = True
    session["email"] = email
    uid = _uid(email)
    existing = _priv_list(f"users/{uid}")
    created = existing[0]["record"].get("created") if existing else _now()
    _priv_put(f"users/{uid}", {"email": email, "created": created, "last_sign_in": _now()})
    if not existing:
        try:
            from .web import notify

            notify("New Basesheet account (someone saved a plan).")
        except Exception:  # noqa: BLE001
            pass
    if payload.get("s"):
        try:
            save_plan(email, payload["s"])
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
    return jsonify(email=current_email(), can_sign_up=can_sign_up())


@bp.get("/api/plans")
def plans_list():
    email = current_email()
    if not email:
        return jsonify(error="Sign in to see your plans."), 401
    return jsonify(plans=list_plans(email))


@bp.post("/api/plans")
def plans_save():
    email = current_email()
    if not email:
        return jsonify(error="Sign in to save plans."), 401
    try:
        return jsonify(plan=save_plan(email, request.get_json(force=True, silent=True) or {}))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@bp.delete("/api/plans/<plan_id>")
def plans_delete(plan_id):
    email = current_email()
    if not email:
        return jsonify(error="Sign in first."), 401
    return jsonify(ok=delete_plan(email, plan_id))
