"""Small, dependency-free security helpers."""
from __future__ import annotations

import re
import time
from collections import deque
from typing import Deque, Dict, Optional


class UploadError(ValueError):
    """Raised for an upload we refuse to process. The message is safe to show."""


# Magic-byte checks: we never trust the client's content-type or file name.
def detect_image_type(data: bytes) -> Optional[str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_upload(data: bytes, max_bytes: int) -> str:
    """Return the detected MIME type or raise UploadError."""
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > max_bytes:
        raise UploadError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    mime = detect_image_type(data)
    if mime is None:
        raise UploadError("Only JPEG, PNG or WebP images are supported.")
    return mime


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_SPACES = re.compile(r"\s+")


def sanitize_text(value: object, max_len: int = 80) -> str:
    """Strip control/bidi characters, collapse whitespace and cap the length.

    Text read from an image is untrusted, so it is cleaned before it is stored
    or returned. The UI also renders it with textContent, never innerHTML.
    """
    if not isinstance(value, str):
        return ""
    cleaned = _CONTROL.sub(" ", value)
    cleaned = _SPACES.sub(" ", cleaned).strip()
    return cleaned[:max_len]


class RateLimiter:
    """Sliding-window limiter kept in memory (per Cloud Run instance)."""

    def __init__(self, limit: int, window_s: float = 60.0, max_keys: int = 10_000):
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        if len(self._hits) > self.max_keys:
            self._prune(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def _prune(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window_s]:
            del self._hits[key]
        if len(self._hits) > self.max_keys:  # still too big: drop everything
            self._hits.clear()


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
