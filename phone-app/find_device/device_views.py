"""
Lumina Device Management API — CRUD for Beckhoff TwinCAT devices.

Endpoints (all under /devices/, JWT required)
──────────────────────────────────────────────────────────
  GET    /devices/           List the user's PLC devices
  POST   /devices/           Add a new PLC device
  GET    /devices/<id>/      Get one device
  PATCH  /devices/<id>/      Update a device
  DELETE /devices/<id>/      Remove a device
  POST   /devices/<id>/test/ Test connectivity to a device
  POST   /devices/<id>/set-default/  Make this the default device
"""
from __future__ import annotations

import logging
import socket
import time

from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from .models import PLCDevice

logger = logging.getLogger("lumina.devices")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _device_dict(dev: PLCDevice) -> dict:
    return {
        "id":           dev.pk,
        "name":         dev.name,
        "description":  dev.description,
        "ip_address":   dev.ip_address,
        "ams_net_id":   dev.ams_net_id,
        "ads_port":     dev.ads_port,
        "is_active":    dev.is_active,
        "is_default":   dev.is_default,
        "created_at":   dev.created_at.isoformat(),
        "updated_at":   dev.updated_at.isoformat(),
        "last_seen_at": dev.last_seen_at.isoformat() if dev.last_seen_at else None,
    }


def _ok(data: dict, status_code: int = 200) -> Response:
    return Response({"ok": True, **data}, status=status_code)


def _err(message: str, code: str = "ERROR", status_code: int = 400) -> Response:
    return Response({"ok": False, "error": message, "code": code}, status=status_code)


def _validate_ams_net_id(value: str) -> bool:
    """Validate AMS Net ID format: x.x.x.x.x.x where each x is 0-255."""
    parts = value.strip().split(".")
    if len(parts) != 6:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# List + Create
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def device_list(request: Request) -> Response:
    if request.method == "GET":
        devices = PLCDevice.objects.filter(owner=request.user)
        return _ok({"devices": [_device_dict(d) for d in devices]})

    # POST — create
    return _create_device(request)


def _create_device(request: Request) -> Response:
    name       = (request.data.get("name") or "").strip()
    ip         = (request.data.get("ip_address") or "").strip()
    ams        = (request.data.get("ams_net_id") or "").strip()
    description = (request.data.get("description") or "").strip()
    ads_port   = request.data.get("ads_port", 851)
    is_default = bool(request.data.get("is_default", False))

    # Validate required fields
    if not name:
        return _err("name is required", "INVALID_PARAM")
    if len(name) > 100:
        return _err("name must be ≤ 100 characters", "INVALID_PARAM")
    if not ip:
        return _err("ip_address is required", "INVALID_PARAM")
    if not ams:
        return _err("ams_net_id is required", "INVALID_PARAM")
    if not _validate_ams_net_id(ams):
        return _err(
            "ams_net_id must be 6 dot-separated octets, e.g. 192.168.0.158.1.1",
            "INVALID_PARAM",
        )
    try:
        ads_port = int(ads_port)
        if not 1 <= ads_port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        return _err("ads_port must be a port number (1-65535)", "INVALID_PARAM")

    if PLCDevice.objects.filter(owner=request.user, name=name).exists():
        return _err(f"You already have a device named '{name}'", "DUPLICATE_NAME", 409)

    # If this is the first device, make it default automatically
    if not PLCDevice.objects.filter(owner=request.user).exists():
        is_default = True

    dev = PLCDevice.objects.create(
        owner=request.user,
        name=name,
        description=description,
        ip_address=ip,
        ams_net_id=ams,
        ads_port=ads_port,
        is_default=is_default,
    )
    logger.info("Device created: %s by %s", name, request.user.username)
    return _ok({"device": _device_dict(dev)}, status_code=201)


# ─────────────────────────────────────────────────────────────────────────────
# Retrieve + Update + Delete
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def device_detail(request: Request, pk: int) -> Response:
    dev = get_object_or_404(PLCDevice, pk=pk, owner=request.user)

    if request.method == "GET":
        return _ok({"device": _device_dict(dev)})

    if request.method == "DELETE":
        name = dev.name
        dev.delete()
        logger.info("Device deleted: %s by %s", name, request.user.username)
        return _ok({"message": f"Device '{name}' deleted"})

    # PATCH — partial update
    updatable = ("name", "description", "ip_address", "ams_net_id", "ads_port", "is_active")
    for field in updatable:
        if field not in request.data:
            continue
        val = request.data[field]
        if field == "name":
            val = str(val).strip()
            if not val:
                return _err("name cannot be empty", "INVALID_PARAM")
            if (
                PLCDevice.objects.filter(owner=request.user, name=val)
                .exclude(pk=dev.pk)
                .exists()
            ):
                return _err(f"Name '{val}' already in use", "DUPLICATE_NAME", 409)
        if field == "ams_net_id":
            if not _validate_ams_net_id(str(val)):
                return _err("Invalid AMS Net ID format", "INVALID_PARAM")
        if field == "ads_port":
            try:
                val = int(val)
                if not 1 <= val <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                return _err("ads_port must be 1-65535", "INVALID_PARAM")
        setattr(dev, field, val)

    dev.save()
    return _ok({"device": _device_dict(dev)})


# ─────────────────────────────────────────────────────────────────────────────
# Set default
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def device_set_default(request: Request, pk: int) -> Response:
    dev = get_object_or_404(PLCDevice, pk=pk, owner=request.user)
    dev.is_default = True
    dev.save()  # model.save() demotes others
    return _ok({"device": _device_dict(dev)})


# ─────────────────────────────────────────────────────────────────────────────
# Connectivity test
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def device_test(request: Request, pk: int) -> Response:
    """
    Quickly probe TCP port 48898 (ADS) and optionally ADS port on the device.
    Does NOT attempt a full ADS handshake — just checks network reachability.
    """
    dev = get_object_or_404(PLCDevice, pk=pk, owner=request.user)

    results: list[dict] = []

    # 1. Ping-style TCP probe on ADS router port 48898
    results.append(_tcp_probe(dev.ip_address, 48898, "ADS router (48898)"))

    # 2. Probe the configured ADS runtime port
    if dev.ads_port != 48898:
        results.append(_tcp_probe(dev.ip_address, dev.ads_port, f"TwinCAT runtime ({dev.ads_port})"))

    reachable = any(r["reachable"] for r in results)

    if reachable:
        dev.last_seen_at = timezone.now()
        dev.save(update_fields=["last_seen_at"])

    return _ok({
        "reachable": reachable,
        "device":    _device_dict(dev),
        "probes":    results,
    })


def _tcp_probe(host: str, port: int, label: str, timeout: float = 3.0) -> dict:
    sw = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = int((time.monotonic() - sw) * 1000)
            return {"label": label, "reachable": True, "latency_ms": ms}
    except (OSError, socket.timeout) as exc:
        ms = int((time.monotonic() - sw) * 1000)
        return {"label": label, "reachable": False, "latency_ms": ms, "error": str(exc)}
