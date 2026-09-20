"""Compatibility entrypoint for ``uv run uvicorn main:app``.

The canonical control-plane application lives under the uv ``src`` layout.
"""

from backend.main import app

__all__ = ["app"]
