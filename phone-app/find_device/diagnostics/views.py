"""
Lumina Diagnostics API — engineering-level system health endpoints.

All endpoints require JWT auth (IsAuthenticated).

GET  /diag/health/              Overall health summary + all device snapshots
GET  /diag/health/<ams_net_id>/ Single device health
GET  /diag/events/              Recent connection events (last 100)
GET  /diag/ads-state/<device_id>/ Live ADS state for a PLCDevice (hits the PLC now)
POST /diag/ads-state/<device_id>/restart-plc/  Send ADS RESET command (admin only)
GET  /diag/symbols/<device_id>/ Symbol count + type breakdown from cache
GET  /diag/performance/         Read/write latency stats across all devices
"""
from __future__ import annotations

import logging
import time

from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from ..models import PLCDevice, DiscoveryCache
from .health import HealthMonitor

logger = logging.getLogger("lumina.diagnostics")

_ADS_TIMEOUT = 5.0   # seconds for live probe calls


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: dict, status_code: int = 200) -> Response:
    return Response({"ok": True, **data}, status=status_code)


def _err(message: str, code: str = "ERROR", status_code: int = 400) -> Response:
    return Response({"ok": False, "error": message, "code": code}, status=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/health/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_summary(request: Request) -> Response:
    """
    Return overall health summary plus snapshots for all tracked devices.

    Response:
      {
        "summary": { total_devices, connected_count, error_count, avg_latency_ms },
        "devices": [ <DeviceHealthSnapshot.to_dict()>, ... ]
      }
    """
    monitor   = HealthMonitor.instance()
    snapshots = monitor.get_all_snapshots()

    return _ok({
        "summary": monitor.summary,
        "devices": [s.to_dict() for s in snapshots],
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/health/<ams_net_id>/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_device(request: Request, ams_net_id: str) -> Response:
    """
    Return the latest health snapshot for a single device identified by AMS Net ID.
    The ams_net_id is URL-encoded in the path (dots are safe in Django path converters).
    """
    monitor  = HealthMonitor.instance()
    snapshot = monitor.get_snapshot(ams_net_id)

    if snapshot is None:
        return _err(
            f"No health data for AMS Net ID '{ams_net_id}'. "
            "Ensure the device is registered and the health monitor is running.",
            "NOT_FOUND",
            404,
        )

    return _ok({"device": snapshot.to_dict()})


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/events/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def event_log(request: Request) -> Response:
    """
    Return the most recent connection events from the rolling event log.

    Query params:
      ams_net_id=<str>   — filter to a specific device
      limit=<int>        — number of events to return (1-100, default 50)
    """
    ams_filter = request.query_params.get("ams_net_id") or None
    try:
        limit = int(request.query_params.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50

    monitor = HealthMonitor.instance()
    events  = monitor.get_event_log(ams_net_id=ams_filter, limit=limit)

    return _ok({
        "count":      len(events),
        "filter":     ams_filter,
        "events":     events,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/ads-state/<device_id>/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_ads_state(request: Request, device_id: int) -> Response:
    """
    Probe a PLCDevice live (new temporary ADS connection, 5 s timeout).

    Returns ads_state, device_name, version, uptime if available.
    The device must belong to the authenticated user.
    """
    dev = get_object_or_404(PLCDevice, pk=device_id, owner=request.user)

    try:
        import pyads  # type: ignore
    except ImportError:
        logger.warning("get_ads_state: pyads not installed — returning mock response")
        return _ok({
            "device_id":   dev.pk,
            "device_name": dev.name,
            "ams_net_id":  dev.ams_net_id,
            "ip_address":  dev.ip_address,
            "ads_state":   "RUN",
            "ads_state_code": 5,
            "device_state":   0,
            "version":     None,
            "mock":        True,
            "latency_ms":  0,
        })

    result = {
        "device_id":      dev.pk,
        "device_name":    dev.name,
        "ams_net_id":     dev.ams_net_id,
        "ip_address":     dev.ip_address,
        "ads_state":      "UNKNOWN",
        "ads_state_code": -1,
        "device_state":   0,
        "version":        None,
        "mock":           False,
        "latency_ms":     None,
    }

    _ADS_STATE_NAMES: dict[int, str] = {
        0: "INVALID", 1: "IDLE", 2: "RESET", 3: "INIT", 4: "START",
        5: "RUN", 6: "STOP", 7: "SAVECFG", 8: "LOADCFG", 9: "POWERFAILURE",
        10: "POWERGOOD", 11: "ERROR", 12: "SHUTDOWN", 13: "SUSPEND",
        14: "RESUME", 15: "CONFIG", 16: "RECONFIG", 17: "STOPPING",
    }

    conn = None
    try:
        conn = pyads.Connection(dev.ams_net_id, dev.ads_port, dev.ip_address)
        conn.open()

        t0 = time.monotonic()

        # Read ADS state
        state_tuple = conn.read_state()
        latency_ms  = round((time.monotonic() - t0) * 1000, 2)

        if state_tuple and len(state_tuple) >= 2:
            ads_code        = int(state_tuple[0])
            result["ads_state_code"] = ads_code
            result["ads_state"]      = _ADS_STATE_NAMES.get(ads_code, f"STATE_{ads_code}")
            result["device_state"]   = int(state_tuple[1])

        result["latency_ms"] = latency_ms

        # Try device info
        try:
            info = conn.get_device_info()
            if info:
                result["device_name"] = getattr(info, "name", dev.name) or dev.name
                major = getattr(info, "major_version", None)
                minor = getattr(info, "minor_version", None)
                build = getattr(info, "version", None)
                if major is not None and minor is not None:
                    result["version"] = f"{major}.{minor}"
                elif build is not None:
                    result["version"] = str(build)
        except Exception as info_exc:
            logger.debug("get_ads_state: device_info failed: %s", info_exc)

    except Exception as exc:
        logger.warning("get_ads_state device_id=%d: %s", device_id, exc)
        return _err(str(exc), "PLC_ERROR", 503)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return _ok(result)


# ─────────────────────────────────────────────────────────────────────────────
# POST /diag/ads-state/<device_id>/restart-plc/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminUser])
def restart_plc(request: Request, device_id: int) -> Response:
    """
    Send an ADS RESET command to a PLCDevice.  Admin only.

    WARNING: This will reset the TwinCAT runtime.  All running programs
    will be stopped momentarily.  Use with caution.
    """
    dev = get_object_or_404(PLCDevice, pk=device_id)

    try:
        import pyads  # type: ignore
    except ImportError:
        return _err("pyads is not installed — cannot send ADS commands", "NOT_AVAILABLE", 503)

    conn = None
    try:
        conn = pyads.Connection(dev.ams_net_id, dev.ads_port, dev.ip_address)
        conn.open()

        # ADS write control: RESET command (state=2 / ADSSTATE_RESET)
        conn.write_control(ads_state=pyads.ADSSTATE_RESET, device_state=0, data=None)

        logger.warning(
            "ADS RESET sent to device '%s' (%s) by admin user '%s'",
            dev.name, dev.ams_net_id, request.user.username,
        )

    except Exception as exc:
        logger.error("restart_plc device_id=%d: %s", device_id, exc)
        return _err(str(exc), "PLC_ERROR", 503)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return _ok({
        "device_id":  dev.pk,
        "device_name": dev.name,
        "ams_net_id": dev.ams_net_id,
        "message":    "ADS RESET command sent successfully",
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/symbols/<device_id>/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_symbols_breakdown(request: Request, device_id: int) -> Response:
    """
    Return symbol count and type/category breakdown from the DiscoveryCache.

    Response:
      {
        "device_id":     int,
        "device_name":   str,
        "scanned_at":    ISO datetime,
        "symbol_count":  int,
        "by_category":   { "lighting": 8, "hvac": 5, ... },
        "by_widget_type":{ "dali_slider": 8, "toggle": 4, ... },
        "by_type_name":  { "REAL": 10, "BOOL": 6, "INT": 4, ... },
        "gvls":          ["gvlDALI", "gvlHVAC", ...]
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

    symbols       = cache.symbols_json or []
    by_category:   dict[str, int] = {}
    by_widget_type: dict[str, int] = {}
    by_type_name:  dict[str, int] = {}
    gvls:          set[str]       = set()

    for sym in symbols:
        cat = sym.get("category") or "other"
        by_category[cat] = by_category.get(cat, 0) + 1

        wt = sym.get("widget_type") or "unknown"
        by_widget_type[wt] = by_widget_type.get(wt, 0) + 1

        tn = sym.get("type_name") or "UNKNOWN"
        by_type_name[tn] = by_type_name.get(tn, 0) + 1

        gvl = sym.get("gvl")
        if gvl:
            gvls.add(gvl)

    return _ok({
        "device_id":      dev.pk,
        "device_name":    dev.name,
        "scanned_at":     cache.scanned_at.isoformat(),
        "scan_duration_ms": cache.scan_duration_ms,
        "symbol_count":   len(symbols),
        "by_category":    dict(sorted(by_category.items(), key=lambda x: -x[1])),
        "by_widget_type": dict(sorted(by_widget_type.items(), key=lambda x: -x[1])),
        "by_type_name":   dict(sorted(by_type_name.items(), key=lambda x: -x[1])),
        "gvls":           sorted(gvls),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /diag/performance/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_performance(request: Request) -> Response:
    """
    Return read/write latency and error statistics aggregated across all devices
    tracked by HealthMonitor.

    Response:
      {
        "device_count": int,
        "devices": [
          {
            "ams_net_id":     str,
            "device_name":    str,
            "connected":      bool,
            "mock":           bool,
            "avg_latency_ms": float,
            "read_count":     int,
            "write_count":    int,
            "error_count":    int,
            "error_rate":     float,
          },
          ...
        ],
        "aggregate": {
          "avg_latency_ms": float,
          "total_reads":    int,
          "total_writes":   int,
          "total_errors":   int,
          "overall_error_rate": float,
        }
      }
    """
    monitor   = HealthMonitor.instance()
    snapshots = monitor.get_all_snapshots()

    device_rows = []
    for s in snapshots:
        device_rows.append({
            "ams_net_id":     s.ams_net_id,
            "device_name":    s.device_name,
            "connected":      s.connected,
            "mock":           s.mock,
            "avg_latency_ms": round(s.avg_latency_ms, 2),
            "read_count":     s.read_count,
            "write_count":    s.write_count,
            "error_count":    s.error_count,
            "error_rate":     round(s.error_rate, 4),
        })

    total_reads   = sum(s.read_count  for s in snapshots)
    total_writes  = sum(s.write_count for s in snapshots)
    total_errors  = sum(s.error_count for s in snapshots)
    total_ops     = total_reads + total_errors
    overall_err_rate = total_errors / total_ops if total_ops > 0 else 0.0

    latencies = [s.avg_latency_ms for s in snapshots if s.avg_latency_ms > 0]
    agg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    return _ok({
        "device_count": len(snapshots),
        "devices":      device_rows,
        "aggregate": {
            "avg_latency_ms":     agg_latency,
            "total_reads":        total_reads,
            "total_writes":       total_writes,
            "total_errors":       total_errors,
            "overall_error_rate": round(overall_err_rate, 4),
        },
    })
