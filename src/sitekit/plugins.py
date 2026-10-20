"""Optional add-ons. The open-source core runs without them; the hosted site
ships the zoning test fit (sitekit.testfit + sitekit.zoning) on top."""

from __future__ import annotations

import importlib.util
from functools import lru_cache


@lru_cache(maxsize=1)
def testfit_available() -> bool:
    return importlib.util.find_spec("sitekit.testfit") is not None and importlib.util.find_spec("sitekit.zoning") is not None
