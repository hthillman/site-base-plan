"""Optional add-ons. The open-source core runs without them; the hosted site
ships the zoning test fit (sitekit.testfit + sitekit.zoning) on top."""

from __future__ import annotations

import importlib.util
from functools import lru_cache


@lru_cache(maxsize=1)
def testfit_available() -> bool:
    return importlib.util.find_spec("sitekit.testfit") is not None and importlib.util.find_spec("sitekit.zoning") is not None


def zoning_summary(site) -> tuple[list[dict], dict | None]:
    """Free zoning lookup (district + headline rules) where the hosted site has rule sheets; ([], None) otherwise."""
    if importlib.util.find_spec("sitekit.zoning") is None:
        return [], None
    from .zoning.summary import summarize

    try:
        return summarize(site)
    except Exception as e:  # noqa: BLE001 - never break a base plan over zoning
        return [{"level": "caution", "text": f"Zoning lookup failed ({type(e).__name__}); the rest of the plan is unaffected."}], None
