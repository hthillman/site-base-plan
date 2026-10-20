"""Vercel entry point: the whole Flask app as one Python function."""

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from sitekit.web import app  # noqa: E402,F401
