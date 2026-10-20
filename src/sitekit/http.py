"""One shared requests session with retries and a polite User-Agent."""

from __future__ import annotations

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "site-base-plan/0.2 (+https://github.com/hthillman/site-base-plan)"
TIMEOUT = 60

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None)
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        s.headers["User-Agent"] = USER_AGENT
        _session = s
    return _session


_plain = None


def plain_session() -> requests.Session:
    """No automatic retries: for services with a fallback, where retries only multiply the wait."""
    global _plain
    if _plain is None:
        s = requests.Session()
        s.mount("https://", HTTPAdapter(max_retries=0, pool_maxsize=16))
        s.headers["User-Agent"] = USER_AGENT
        _plain = s
    return _plain


# The ArcGIS key is restricted to the site's referrer; server-side calls must
# send it explicitly.
ESRI_REFERER = os.environ.get("ESRI_REFERER", "")


def esri_headers() -> dict:
    return {"Referer": ESRI_REFERER} if ESRI_REFERER else {}


def get_json(url: str, params: dict | None = None, timeout: int = TIMEOUT, headers: dict | None = None) -> dict:
    r = session().get(url, params=params, timeout=timeout, headers=headers)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data and isinstance(data["error"], dict):
        err = data["error"]
        raise RuntimeError(f"{url}: {err.get('code')} {err.get('message')} {err.get('details') or ''}".strip())
    return data
