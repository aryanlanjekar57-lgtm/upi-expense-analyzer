"""Runtime settings, read from environment variables (never from the repo)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    max_upload_bytes: int
    max_files: int
    rate_limit_per_minute: int
    gemini_timeout_s: float


def get_settings() -> Settings:
    """Read settings fresh on each call so tests can change the environment."""
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        # "-latest" aliases keep working when a specific model version is retired.
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip(),
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
        max_files=_int("MAX_FILES", 5),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 20),
        gemini_timeout_s=float(_int("GEMINI_TIMEOUT_S", 30)),
    )
