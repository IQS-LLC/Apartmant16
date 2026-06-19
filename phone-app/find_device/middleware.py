"""
Production middleware for Lumina PLC backend.

Provides:
  - RequestLoggingMiddleware  — structured request/response logging
  - RateLimitMiddleware       — per-IP sliding-window rate limit
  - APIKeyMiddleware          — optional bearer/header auth (set API_KEY env var)
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Callable, Deque

from django.conf import settings
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger("lumina.http")


# ── Request / Response logging ────────────────────────────────────────────────

class RequestLoggingMiddleware:
    """
    Logs every API request with method, path, status, and latency.
    Excludes static/media files to keep logs clean.
    """

    SKIP_PREFIXES = ("/static/", "/media/", "/favicon")

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if any(request.path.startswith(p) for p in self.SKIP_PREFIXES):
            return self.get_response(request)

        t0 = time.perf_counter()
        response = self.get_response(request)
        ms = round((time.perf_counter() - t0) * 1000)

        ip = _get_client_ip(request)
        logger.info(
            "%s %s %d %dms  ip=%s",
            request.method, request.path, response.status_code, ms, ip,
        )
        return response


# ── Rate limiting ─────────────────────────────────────────────────────────────

class RateLimitMiddleware:
    """
    Sliding-window in-memory rate limiter.

    Defaults (configurable in settings.py):
      RATE_LIMIT_REQUESTS = 120   # max requests per window
      RATE_LIMIT_WINDOW   = 60    # window size in seconds

    Returns 429 when exceeded.  POST endpoints are limited more strictly
    (writes to PLC hardware should not be hammered).
    """

    _DEFAULT_LIMIT  = 120    # GETs per window
    _WRITE_LIMIT    = 60     # POSTs per window  (writes to PLC)
    _WINDOW_SECONDS = 60

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        self._lock   = threading.Lock()
        # ip → deque of timestamps
        self._hits:   dict[str, Deque[float]] = collections.defaultdict(
            lambda: collections.deque()
        )
        self._limit  = getattr(settings, "RATE_LIMIT_REQUESTS", self._DEFAULT_LIMIT)
        self._wlimit = getattr(settings, "RATE_LIMIT_WRITE_REQUESTS", self._WRITE_LIMIT)
        self._window = getattr(settings, "RATE_LIMIT_WINDOW", self._WINDOW_SECONDS)

    def __call__(self, request: HttpRequest):
        if not request.path.startswith("/plc/"):
            return self.get_response(request)

        ip    = _get_client_ip(request)
        limit = self._wlimit if request.method == "POST" else self._limit
        now   = time.monotonic()

        with self._lock:
            dq = self._hits[ip]
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                logger.warning(
                    "Rate limit exceeded  ip=%s  path=%s  method=%s",
                    ip, request.path, request.method,
                )
                return JsonResponse(
                    {
                        "ok": False,
                        "error": "Rate limit exceeded. Please slow down.",
                        "code": "RATE_LIMITED",
                        "retry_after": self._window,
                    },
                    status=429,
                )
            dq.append(now)

        return self.get_response(request)


# ── Optional API-key auth ─────────────────────────────────────────────────────

class APIKeyMiddleware:
    """
    Optional bearer/header API-key authentication.

    Enabled only when the API_KEY environment variable is set.
    Accepts the key via:
      - Header:      X-API-Key: <key>
      - Query param: ?api_key=<key>

    Skips the health check and Django admin paths.
    """

    SKIP_PATHS = ("/health/", "/admin/", "/static/", "/media/")

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        import os
        self._key = os.getenv("API_KEY", "")

    def __call__(self, request: HttpRequest):
        if not self._key:
            # Auth not configured — pass through
            return self.get_response(request)

        if any(request.path.startswith(p) for p in self.SKIP_PATHS):
            return self.get_response(request)

        provided = (
            request.headers.get("X-Api-Key", "")
            or request.GET.get("api_key", "")
        )

        if not _constant_time_compare(provided, self._key):
            logger.warning(
                "API key rejected  ip=%s  path=%s",
                _get_client_ip(request), request.path,
            )
            return JsonResponse(
                {
                    "ok":    False,
                    "error": "Unauthorized. Provide a valid X-Api-Key header.",
                    "code":  "UNAUTHORIZED",
                },
                status=401,
            )

        return self.get_response(request)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_ip(request: HttpRequest) -> str:
    """Extract the real client IP, respecting reverse-proxy headers."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks."""
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())
