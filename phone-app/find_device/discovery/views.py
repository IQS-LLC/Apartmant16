"""
Lumina Discovery API — enumerate and cache TwinCAT 3 symbols.

Endpoints (under /discovery/, JWT required)
──────────────────────────────────────────────────────────────────────────
  POST /discovery/<device_id>/scan/     Run (or re-run) discovery, cache results
  GET  /discovery/<device_id>/symbols/  Return cached symbols (with optional filter)
  GET  /discovery/<device_id>/widgets/  Return widget layout grouped by GVL / category
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ..models import PLCDevice, DiscoveryCache
from .scanner import SymbolScanner
from .classifier import classify_batch

logger = logging.getLogger("lumina.discovery")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: dict, status_code: int = 200) -> Response:
    return Response({"ok": True, **data}, status=status_code)


def _err(message: str, code: str = "ERROR", status_code: int = 400) -> Response:
    return Response({"ok": False, "error": message, "code": code}, status=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Scan
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def scan(request: Request, device_id: int) -> Response:
    """
    Trigger a fresh symbol discovery scan on the given PLCDevice.
    Results are stored in DiscoveryCache and returned immediately.

    Query params:
      mock=true  — force mock data (useful for testing without a live PLC)
    """
    dev = get_object_or_404(PLCDevice, pk=device_id, owner=request.user)

    force_mock = request.query_params.get("mock", "").lower() == "true"

    # Determine whether to use mock data:
    # use mock if the device IP is a loopback / test address, or if forced
    use_mock = force_mock or _is_mock_address(dev.ip_address)

    scanner = SymbolScanner(
        ip=dev.ip_address,
        ams_net_id=dev.ams_net_id,
        ads_port=dev.ads_port,
        mock=use_mock,
    )

    try:
        raw_symbols, duration_ms = scanner.scan()
    except ConnectionError as exc:
        logger.error("Discovery scan failed for device %d: %s", device_id, exc)
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("Discovery scan unexpected error for device %d", device_id)
        return _err(str(exc), "SERVER_ERROR", 500)

    classified = classify_batch(raw_symbols)
    symbols_json = [s.to_dict() for s in classified]

    cache, _ = DiscoveryCache.objects.update_or_create(
        device=dev,
        defaults={
            "symbols_json":     symbols_json,
            "scan_duration_ms": duration_ms,
            "symbol_count":     len(symbols_json),
        },
    )

    logger.info(
        "Discovery: %d symbols for device '%s' in %dms  mock=%s",
        len(symbols_json), dev.name, duration_ms, use_mock,
    )

    return _ok({
        "device_id":     dev.pk,
        "device_name":   dev.name,
        "symbol_count":  len(symbols_json),
        "duration_ms":   duration_ms,
        "mock":          use_mock,
        "symbols":       symbols_json,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Cached symbols
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def symbols(request: Request, device_id: int) -> Response:
    """
    Return cached symbols for a device.

    Query params:
      category=lighting|hvac|alarms|…   — filter by category
      widget_type=toggle|dali_slider|…  — filter by widget type
      q=<text>                          — search by label or name
    """
    dev = get_object_or_404(PLCDevice, pk=device_id, owner=request.user)

    try:
        cache = dev.discovery_cache
    except DiscoveryCache.DoesNotExist:
        return _err(
            "No discovery data found. Run POST /discovery/<id>/scan/ first.",
            "NO_CACHE",
            404,
        )

    syms = list(cache.symbols_json)

    # Apply filters
    if cat := request.query_params.get("category"):
        syms = [s for s in syms if s.get("category") == cat]
    if wt := request.query_params.get("widget_type"):
        syms = [s for s in syms if s.get("widget_type") == wt]
    if q := request.query_params.get("q", "").lower():
        syms = [
            s for s in syms
            if q in s.get("label", "").lower() or q in s.get("name", "").lower()
        ]

    return _ok({
        "device_id":    dev.pk,
        "device_name":  dev.name,
        "symbol_count": len(syms),
        "scanned_at":   cache.scanned_at.isoformat(),
        "symbols":      syms,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Widget layout (grouped for UI rendering)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def widget_layout(request: Request, device_id: int) -> Response:
    """
    Return symbols grouped by category and GVL — optimised for Flutter
    dynamic dashboard rendering.

    Response structure:
      {
        "groups": [
          {
            "id":    "gvlDALI",
            "title": "Lighting",
            "category": "lighting",
            "widgets": [ <symbol_dict>, ... ]
          },
          ...
        ]
      }
    """
    dev = get_object_or_404(PLCDevice, pk=device_id, owner=request.user)

    try:
        cache = dev.discovery_cache
    except DiscoveryCache.DoesNotExist:
        return _err(
            "No discovery data found. Run POST /discovery/<id>/scan/ first.",
            "NO_CACHE",
            404,
        )

    # Group by GVL
    groups: dict[str, dict] = {}
    for sym in cache.symbols_json:
        gvl = sym.get("gvl") or "Other"
        if gvl not in groups:
            groups[gvl] = {
                "id":       gvl,
                "title":    _gvl_title(gvl),
                "category": sym.get("category", "other"),
                "widgets":  [],
            }
        groups[gvl]["widgets"].append(sym)

    # Sort groups: known categories first, then alphabetical
    category_order = ["lighting", "hvac", "relays", "sensors", "energy", "alarms", "other"]
    sorted_groups = sorted(
        groups.values(),
        key=lambda g: (
            category_order.index(g["category"])
            if g["category"] in category_order
            else len(category_order),
            g["title"],
        ),
    )

    return _ok({
        "device_id":   dev.pk,
        "device_name": dev.name,
        "scanned_at":  cache.scanned_at.isoformat(),
        "groups":      sorted_groups,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_GVL_TITLES: dict[str, str] = {
    "gvlDALI":    "Lighting",
    "gvlHVAC":   "Climate",
    "gvlAlarms": "Alarms",
    "gvlRelays": "Switches & Relays",
    "gvlSwitch": "Wall Switches",
    "gvlInput":  "Inputs",
    "gvlOutput": "Outputs",
    "gvlSensor": "Sensors",
    "gvlMotor":  "Motors",
    "gvlPump":   "Pumps",
    "gvlValve":  "Valves",
    "gvlEnergy": "Energy",
}


def _gvl_title(gvl: str) -> str:
    return _GVL_TITLES.get(gvl, gvl)


def _is_mock_address(ip: str) -> bool:
    """Return True for loopback or obviously test addresses."""
    return ip.startswith("127.") or ip in ("0.0.0.0", "localhost", "::1")
