"""Single application identity shared by API responses and scientific exports."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "AstroDoncel Studio"
APP_VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
