"""
Lumina Real-Time SSE Endpoint — Server-Sent Events for live variable updates.

GET /realtime/<device_id>/stream/   — SSE stream of variable change events
GET /realtime/<device_id>/snapshot/ — Current values of all monitored variables (REST)

The SSE stream pushes:
  data: {"type": "variable_change", "var_name": "...", "value": ..., "ts": 1234567890.123}
  data: {"type": "connection_change", "connected": true, "ads_state": "RUN"}
  data: {"type": "heartbeat", "ts": 1234567890.123}
  data: {"type": "alarm", "var_name": "...", "active": true, "label": "Smoke Detector"}

The client must pass JWT in query param ?token=<access_token> since EventSource
in browsers/Flutter doesn't support custom headers. Validate the token manually
using simplejwt's AccessToken class.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from typing import Generator, Optional

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ..models import PLCDevice

try:
    from .event_bus import EventBus
except ImportError:
    EventBus = None  # type: ignore

logger = logging.getLogger("lumina.realtime")

# Maximum concurrent SSE connections per device
_MAX_SSE_CONNECTIONS_PER_DEVICE = 50

# Heartbeat interval — seconds to wait on queue before emitting a heartbeat
_HEARTBEAT_TIMEOUT_S = 15.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: dict, status_code: int = 200) -> Response:
    return Response({"ok": True, **data}, status=status_code)


def _err(message: str, code: str = "ERROR", status_code: int = 400) -> Response:
    return Response({"ok": False, "error": message, "code": code}, status=status_code)


def _sse_line(event_dict: dict) -> str:
    """Format a dict as an SSE `data:` line followed by double newline."""
    return f"data: {json.dumps(event_dict)}\n\n"


def _validate_jwt_token(token_str: str) -> Optional[object]:
    """
    Validate a JWT access token string using simplejwt.

    Returns the Django User object on success, or None on failure.
    """
    if not token_str:
        return None
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth.models import User

        validated = AccessToken(token_str)
        user_id   = validated.payload.get("user_id")
        if user_id is None:
            return None
        return User.objects.get(pk=user_id)
    except Exception as exc:
        logger.debug("JWT validation failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-device SSE connection counter
# ─────────────────────────────────────────────────────────────────────────────

class _SSEConnectionRegistry:
    """
    Tracks the number of active SSE connections per device_id.

    This is separate from EventBus so we can enforce per-device connection caps
    regardless of how the EventBus counts clients.
    """

    _instance:      Optional['_SSEConnectionRegistry'] = None
    _instance_lock: threading.Lock                     = threading.Lock()

    @classmethod
    def instance(cls) -> '_SSEConnectionRegistry':
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._counts: dict[int, int] = {}
        self._lock   = threading.RLock()

    def increment(self, device_id: int) -> int:
        with self._lock:
            self._counts[device_id] = self._counts.get(device_id, 0) + 1
            return self._counts[device_id]

    def decrement(self, device_id: int) -> int:
        with self._lock:
            count = max(0, self._counts.get(device_id, 0) - 1)
            if count == 0:
                self._counts.pop(device_id, None)
            else:
                self._counts[device_id] = count
            return count

    def count(self, device_id: int) -> int:
        with self._lock:
            return self._counts.get(device_id, 0)


# ─────────────────────────────────────────────────────────────────────────────
# DeviceValueCache — last-known values per device
# ─────────────────────────────────────────────────────────────────────────────

class DeviceValueCache:
    """
    Singleton in-memory cache of last-known variable values per device.

    Updated by the EventBus publisher whenever a variable_change event is
    dispatched (e.g. via event_bus.publish()).  The snapshot endpoint reads
    from here to return instantaneous state without a live PLC round-trip.

    Keyed as: _store[device_id][var_name] = {"value": ..., "ts": float}
    """

    _instance:      Optional['DeviceValueCache'] = None
    _instance_lock: threading.Lock               = threading.Lock()

    @classmethod
    def instance(cls) -> 'DeviceValueCache':
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._store: dict[int, dict[str, dict]] = {}
        self._lock  = threading.RLock()

    def update(self, device_id: int, var_name: str, value, ts: float | None = None) -> None:
        """Store (or overwrite) the last-known value for a variable."""
        with self._lock:
            if device_id not in self._store:
                self._store[device_id] = {}
            self._store[device_id][var_name] = {
                "value": value,
                "ts":    ts if ts is not None else time.time(),
            }

    def get_all(self, device_id: int) -> dict[str, dict]:
        """Return a snapshot dict of all known variables for device_id."""
        with self._lock:
            return dict(self._store.get(device_id, {}))

    def get(self, device_id: int, var_name: str) -> dict | None:
        """Return the cached entry for a single variable, or None."""
        with self._lock:
            return self._store.get(device_id, {}).get(var_name)

    def clear_device(self, device_id: int) -> None:
        """Purge all cached values for device_id (e.g. after a discovery rescan)."""
        with self._lock:
            self._store.pop(device_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# SSE stream generator
# ─────────────────────────────────────────────────────────────────────────────

def _sse_generator(
    device_id: int,
    client_id: str,
    event_queue: queue.Queue,
) -> Generator[str, None, None]:
    """
    Generator that yields SSE-formatted strings until the client disconnects.

    - Blocks on event_queue with a _HEARTBEAT_TIMEOUT_S timeout.
    - On timeout, sends a heartbeat event to keep the connection alive.
    - On GeneratorExit (client disconnect), cleans up EventBus registration
      and decrements the per-device connection counter.
    """
    conn_registry = _SSEConnectionRegistry.instance()
    bus = EventBus.instance() if EventBus is not None else None

    try:
        # Initial acknowledgement
        yield _sse_line({
            "type":      "connection_acknowledged",
            "device_id": device_id,
            "client_id": client_id,
            "ts":        time.time(),
        })

        while True:
            try:
                event = event_queue.get(timeout=_HEARTBEAT_TIMEOUT_S)

                # Mirror variable_change events into DeviceValueCache
                if event.get("type") == "variable_change":
                    DeviceValueCache.instance().update(
                        device_id,
                        event.get("var_name", ""),
                        event.get("value"),
                        event.get("timestamp") or event.get("ts"),
                    )

                yield _sse_line(event)

            except queue.Empty:
                # No event within the timeout window — emit heartbeat
                yield _sse_line({
                    "type": "heartbeat",
                    "ts":   time.time(),
                })

    except GeneratorExit:
        logger.debug("SSE client %s disconnected from device %d", client_id, device_id)
    finally:
        # Always clean up, even if an exception escapes the loop
        if bus is not None:
            bus.unregister_client(client_id)
        conn_registry.decrement(device_id)


# ─────────────────────────────────────────────────────────────────────────────
# GET /realtime/<device_id>/stream/
# ─────────────────────────────────────────────────────────────────────────────

def sse_stream(request, device_id: int) -> StreamingHttpResponse:
    """
    SSE stream of live variable-change events for a PLCDevice.

    Authentication: JWT passed via ?token=<access_token> query parameter.
    EventSource in browsers and Flutter's http package cannot set custom
    headers, so we validate the token manually from the query string.

    Returns 401 if the token is missing or invalid.
    Returns 503 if the per-device connection limit is reached.
    Returns text/event-stream on success.
    """
    from django.http import JsonResponse

    # ── JWT auth via query param ──────────────────────────────────────────────
    token_str = request.GET.get("token", "").strip()
    user      = _validate_jwt_token(token_str)
    if user is None:
        return JsonResponse(
            {"ok": False, "error": "Invalid or missing token", "code": "UNAUTHORIZED"},
            status=401,
        )

    # ── Device ownership check ───────────────────────────────────────────────
    try:
        dev = PLCDevice.objects.get(pk=device_id, owner=user)
    except PLCDevice.DoesNotExist:
        return JsonResponse(
            {"ok": False, "error": "Device not found", "code": "NOT_FOUND"},
            status=404,
        )

    # ── Connection cap ────────────────────────────────────────────────────────
    conn_registry = _SSEConnectionRegistry.instance()
    if conn_registry.count(device_id) >= _MAX_SSE_CONNECTIONS_PER_DEVICE:
        logger.warning(
            "SSE connection refused for device %d: limit %d reached",
            device_id, _MAX_SSE_CONNECTIONS_PER_DEVICE,
        )
        return JsonResponse(
            {
                "ok":    False,
                "error": (
                    f"Too many concurrent SSE connections for this device "
                    f"(max {_MAX_SSE_CONNECTIONS_PER_DEVICE})"
                ),
                "code": "TOO_MANY_CONNECTIONS",
            },
            status=503,
        )

    # ── Register with EventBus ────────────────────────────────────────────────
    if EventBus is None:
        # pyads or event_bus not available — return an empty graceful stream
        logger.warning("SSE stream requested but EventBus is unavailable")
        return JsonResponse(
            {"ok": False, "error": "Real-time subsystem not available", "code": "NOT_AVAILABLE"},
            status=503,
        )

    client_id   = str(uuid.uuid4())
    bus         = EventBus.instance()
    event_queue = bus.register_client(client_id)

    conn_registry.increment(device_id)

    logger.info(
        "SSE stream opened: device=%d client=%s user=%s connections=%d",
        device_id, client_id, user.username, conn_registry.count(device_id),
    )

    response = StreamingHttpResponse(
        _sse_generator(device_id, client_id, event_queue),
        content_type="text/event-stream",
    )
    response["Cache-Control"]     = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["Connection"]        = "keep-alive"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# GET /realtime/<device_id>/snapshot/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def snapshot(request: Request, device_id: int) -> Response:
    """
    Return the current known values for all monitored variables on a device.

    Values are sourced from DeviceValueCache which is populated as SSE
    clients receive variable_change events from EventBus.  On first access
    (before any events have been received) the dict will be empty.

    Response:
      {
        "device_id":       int,
        "device_name":     str,
        "variable_count":  int,
        "variables": {
          "gvlDALI.nBrightness_1": {"value": 75, "ts": 1234567890.123},
          ...
        }
      }
    """
    dev = get_object_or_404(PLCDevice, pk=device_id, owner=request.user)

    cache     = DeviceValueCache.instance()
    variables = cache.get_all(device_id)

    return _ok({
        "device_id":      dev.pk,
        "device_name":    dev.name,
        "variable_count": len(variables),
        "variables":      variables,
    })
