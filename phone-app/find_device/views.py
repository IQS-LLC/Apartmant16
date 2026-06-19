"""
Lumina PLC REST API — production views.

Endpoints
─────────────────────────────────────────────────────────────
  GET  /plc/                              health + PLC status
  GET  /plc/state/                        full system state  (polled every 2 s)
  GET  /plc/devices/                      device metadata
  GET  /plc/diagnostics/                  detailed diagnostics

  POST /plc/dali/<ch>/brightness/         set single DALI channel
  POST /plc/dali/all/brightness/          set all DALI channels
  POST /plc/room/<room>/brightness/       set all DALI channels in a room

  POST /plc/relay/<ch>/                   set wall relay (state=on|off)

  POST /plc/curtain/<idx>/               set curtain motor (cmd=stop|up|down)
  POST /plc/curtain/all/                  stop all curtains

  POST /plc/appliance/<gvl_name>/         set appliance relay (state=on|off)

  GET  /plc/sensors/                      all sensor states (magnetic + motion)
  POST /plc/security/alarm/               arm/disarm (armed=true|false)
  POST /plc/security/lockdown/            activate/deactivate lockdown

Request format  : application/x-www-form-urlencoded
Response format : JSON  { ok, data/error, ts }

Error codes
  INVALID_PARAM   — bad / missing input parameter
  NOT_FOUND       — device not configured in registry
  PLC_ERROR       — hardware / ADS error
  SERVER_ERROR    — unexpected internal error
"""
from __future__ import annotations

import logging
import time
import urllib.parse

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .plc.registry import DeviceRegistry
from .plc.devices import CurtainMotor

logger = logging.getLogger("lumina.api")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> float:
    return round(time.time(), 3)

def _ok(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data, "ts": _ts()}, status=status)

def _err(message: str, code: str = "SERVER_ERROR", status: int = 500) -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": message, "code": code, "ts": _ts()}, status=status)

def _registry() -> DeviceRegistry:
    return DeviceRegistry.instance()

def _parse_brightness(post_data):
    raw = post_data.get("brightness")
    if raw is None:
        return None, _err("Missing required parameter: brightness", "INVALID_PARAM", 400)
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return None, _err(
            f"brightness must be an integer 0-100, got: {raw!r}", "INVALID_PARAM", 400)
    if not 0 <= pct <= 100:
        return None, _err(f"brightness must be 0-100, got: {pct}", "INVALID_PARAM", 400)
    return pct, None

def _parse_bool_param(post_data, param: str):
    raw = post_data.get(param, "").lower().strip()
    if not raw:
        return None, _err(f"Missing required parameter: {param}", "INVALID_PARAM", 400)
    if raw not in ("true", "false", "1", "0", "on", "off"):
        return None, _err(
            f"{param} must be true/false/on/off/1/0", "INVALID_PARAM", 400)
    return raw in ("true", "1", "on"), None


# ── Health ────────────────────────────────────────────────────────────────────

def health(request):
    try:
        r = _registry()
        plc_connected, mock = r.connected, r.mock
    except Exception:
        plc_connected, mock = False, True

    return JsonResponse({
        "status": "ok",
        "plc":    "connected" if plc_connected else "disconnected",
        "mock":   mock,
        "ts":     _ts(),
        "version": "3.0",
    })


# ── Full state ────────────────────────────────────────────────────────────────

@require_GET
def get_state(request):
    try:
        state = _registry().read_full_state()
        return JsonResponse({**state, "ts": _ts()})
    except ConnectionError as exc:
        logger.error("get_state: PLC unreachable: %s", exc)
        return _err(f"PLC unreachable: {exc}", "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("get_state: unexpected error")
        return _err(f"Internal error: {exc}", "SERVER_ERROR", 500)


# ── Device metadata ───────────────────────────────────────────────────────────

@require_GET
def get_devices(request):
    r = _registry()
    return JsonResponse({
        "apartment_id":   r.apartment_id,
        "dali":           [d.to_dict() for d in r.all_dali()],
        "relays":         [d.to_dict() for d in r.all_relays()],
        "curtains":       [d.to_dict() for d in r.all_curtains()],
        "switches":       [s.to_dict() for s in r.all_switches()],
        "appliances":     [a.to_dict() for a in r.all_appliances()],
        "door_sensors":   [s.to_dict() for s in r.all_door_sensors()],
        "window_sensors": [s.to_dict() for s in r.all_window_sensors()],
        "motion_sensors": [s.to_dict() for s in r.all_motion_sensors()],
        "rooms":          r.rooms(),
        "ts":             _ts(),
    })


# ── Diagnostics ───────────────────────────────────────────────────────────────

@require_GET
def get_diagnostics(request):
    try:
        r     = _registry()
        state = r.read_full_state()

        return _ok({
            "plc_connected":   r.connected,
            "mock":            r.mock,
            "apartment_id":    r.apartment_id,
            "dali_channels":   len(r.all_dali()),
            "relay_channels":  len(r.all_relays()),
            "curtain_motors":  len(r.all_curtains()),
            "switch_inputs":   len(r.all_switches()),
            "appliances":      len(r.all_appliances()),
            "door_sensors":    len(r.all_door_sensors()),
            "window_sensors":  len(r.all_window_sensors()),
            "motion_sensors":  len(r.all_motion_sensors()),
            "rooms":           r.rooms(),
            "dali": [
                {"channel": dev.channel, "name": dev.name, "room": dev.room,
                 "brightness": state["dali"].get(dev.channel),
                 "ok": state["dali"].get(dev.channel) is not None}
                for dev in r.all_dali()
            ],
            "relays": [
                {"channel": dev.channel, "name": dev.name, "room": dev.room,
                 "on": state["relays"].get(dev.channel),
                 "ok": state["relays"].get(dev.channel) is not None}
                for dev in r.all_relays()
            ],
            "curtains": [
                {"index": dev.index, "name": dev.name, "room": dev.room,
                 "state": state["curtains"].get(dev.index),
                 "ok": state["curtains"].get(dev.index) is not None}
                for dev in r.all_curtains()
            ],
            "security": state.get("security", {}),
        })
    except Exception as exc:
        logger.exception("get_diagnostics: unexpected error")
        return _err(str(exc), "SERVER_ERROR", 500)


# ── DALI — single channel ─────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_dali_brightness(request, channel: int):
    if not 1 <= channel <= 16:
        return _err(f"DALI channel must be 1-16, got {channel}", "INVALID_PARAM", 400)

    pct, err = _parse_brightness(request.POST)
    if err:
        return err

    dev = _registry().dali(channel)
    if dev is None:
        return _err(f"DALI channel {channel} not configured", "NOT_FOUND", 404)

    try:
        dev.set_brightness(pct)
        logger.info("DALI ch%d → %d%%", channel, pct)
        return _ok({"channel": channel, "brightness": pct})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_dali_brightness ch%d", channel)
        return _err(str(exc), "SERVER_ERROR", 500)


# ── DALI — all channels ───────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_dali_brightness_all(request):
    pct, err = _parse_brightness(request.POST)
    if err:
        return err

    r, errors = _registry(), []
    for dev in r.all_dali():
        try:
            dev.set_brightness(pct)
        except Exception as exc:
            errors.append({"channel": dev.channel, "error": str(exc)})
            logger.error("set_all_brightness ch%d: %s", dev.channel, exc)

    if errors:
        return JsonResponse({
            "ok": False, "data": {"brightness": pct, "errors": errors},
            "error": f"{len(errors)} channel(s) failed",
            "code": "PARTIAL_FAILURE", "ts": _ts(),
        }, status=207)

    logger.info("set_all_brightness → %d%%", pct)
    return _ok({"brightness": pct, "channels": len(r.all_dali())})


# ── DALI — room brightness ────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_room_brightness(request, room_name: str):
    room = urllib.parse.unquote(room_name).strip()
    if not room:
        return _err("Room name cannot be empty", "INVALID_PARAM", 400)

    pct, err = _parse_brightness(request.POST)
    if err:
        return err

    r       = _registry()
    devices = [d for d in r.all_dali() if d.room.lower() == room.lower()]

    if not devices:
        return _err(
            f"Room '{room}' not found. Available: {r.rooms()}",
            "NOT_FOUND", 404)

    errors = []
    for dev in devices:
        try:
            dev.set_brightness(pct)
        except Exception as exc:
            errors.append({"channel": dev.channel, "error": str(exc)})
            logger.error("set_room_brightness %s ch%d: %s", room, dev.channel, exc)

    if errors:
        return JsonResponse({
            "ok": False,
            "data": {"room": room, "brightness": pct, "errors": errors},
            "error": f"{len(errors)} channel(s) in '{room}' failed",
            "code": "PARTIAL_FAILURE", "ts": _ts(),
        }, status=207)

    logger.info("set_room_brightness '%s' → %d%%", room, pct)
    return _ok({"room": room, "brightness": pct, "channels": len(devices)})


# ── Wall relay ────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_relay(request, channel: int):
    if not 1 <= channel <= 16:
        return _err(f"Relay channel must be 1-16, got {channel}", "INVALID_PARAM", 400)

    on, err = _parse_bool_param(request.POST, "state")
    if err:
        return err

    dev = _registry().relay(channel)
    if dev is None:
        return _err(f"Relay channel {channel} not configured", "NOT_FOUND", 404)

    try:
        dev.set_state(on)
        logger.info("Relay ch%d → %s", channel, "ON" if on else "OFF")
        return _ok({"channel": channel, "on": on})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_relay ch%d", channel)
        return _err(str(exc), "SERVER_ERROR", 500)


# ── Curtain motor ─────────────────────────────────────────────────────────────

_CURTAIN_CMD_MAP = {
    "stop": CurtainMotor.STOP,
    "0":    CurtainMotor.STOP,
    "up":   CurtainMotor.UP,
    "1":    CurtainMotor.UP,
    "down": CurtainMotor.DOWN,
    "2":    CurtainMotor.DOWN,
}

@csrf_exempt
@require_POST
def set_curtain(request, index: int):
    if not 1 <= index <= 16:
        return _err(f"Curtain index must be 1-16, got {index}", "INVALID_PARAM", 400)

    raw = request.POST.get("cmd", "").lower().strip()
    if raw not in _CURTAIN_CMD_MAP:
        return _err(
            "cmd must be 'stop'/'up'/'down' (or 0/1/2)", "INVALID_PARAM", 400)
    cmd = _CURTAIN_CMD_MAP[raw]

    dev = _registry().curtain(index)
    if dev is None:
        return _err(f"Curtain {index} not configured", "NOT_FOUND", 404)

    try:
        dev.set_command(cmd)
        logger.info("Curtain %d → %s (%d)", index, raw, cmd)
        return _ok({"index": index, "cmd": cmd})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_curtain %d", index)
        return _err(str(exc), "SERVER_ERROR", 500)


@csrf_exempt
@require_POST
def set_curtain_all(request):
    raw = request.POST.get("cmd", "stop").lower().strip()
    if raw not in _CURTAIN_CMD_MAP:
        return _err("cmd must be 'stop'/'up'/'down'", "INVALID_PARAM", 400)
    cmd = _CURTAIN_CMD_MAP[raw]

    r, errors = _registry(), []
    for dev in r.all_curtains():
        try:
            dev.set_command(cmd)
        except Exception as exc:
            errors.append({"index": dev.index, "error": str(exc)})

    if errors:
        return JsonResponse({
            "ok": False, "data": {"cmd": cmd, "errors": errors},
            "error": f"{len(errors)} curtain(s) failed",
            "code": "PARTIAL_FAILURE", "ts": _ts(),
        }, status=207)

    logger.info("set_curtain_all → %s (%d)", raw, cmd)
    return _ok({"cmd": cmd, "count": len(r.all_curtains())})


# ── Appliance ─────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_appliance(request, gvl_name: str):
    on, err = _parse_bool_param(request.POST, "state")
    if err:
        return err

    dev = _registry().appliance(gvl_name)
    if dev is None:
        from .plc.devices import APPLIANCE_NAMES
        return _err(
            f"Appliance '{gvl_name}' not configured. "
            f"Available: {list(_registry()._appliances.keys())}",
            "NOT_FOUND", 404)

    try:
        dev.set_state(on)
        logger.info("Appliance %s → %s", gvl_name, "ON" if on else "OFF")
        return _ok({"gvl_name": gvl_name, "on": on})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_appliance %s", gvl_name)
        return _err(str(exc), "SERVER_ERROR", 500)


# ── Sensors ───────────────────────────────────────────────────────────────────

@require_GET
def get_sensors(request):
    """Returns live states of all magnetic and motion sensors."""
    try:
        r = _registry()
        return _ok({
            "door_sensors":   {idx: dev.read_state() for idx, dev in r._door_sensors.items()},
            "window_sensors": {idx: dev.read_state() for idx, dev in r._window_sensors.items()},
            "motion_sensors": {idx: dev.read_state() for idx, dev in r._motion_sensors.items()},
        })
    except Exception as exc:
        logger.exception("get_sensors: unexpected error")
        return _err(str(exc), "SERVER_ERROR", 500)


# ── Security — alarm ──────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_alarm(request):
    armed, err = _parse_bool_param(request.POST, "armed")
    if err:
        return err

    sec = _registry().security()
    if sec is None:
        return _err("Security controller not initialised", "SERVER_ERROR", 500)

    try:
        sec.set_alarm_armed(armed)
        logger.info("Alarm → %s", "ARMED" if armed else "DISARMED")
        return _ok({"armed": armed})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_alarm")
        return _err(str(exc), "SERVER_ERROR", 500)


# ── Security — lockdown ───────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def set_lockdown(request):
    active, err = _parse_bool_param(request.POST, "active")
    if err:
        return err

    sec = _registry().security()
    if sec is None:
        return _err("Security controller not initialised", "SERVER_ERROR", 500)

    try:
        sec.set_lockdown(active)
        logger.info("Lockdown → %s", "ACTIVE" if active else "INACTIVE")
        return _ok({"lockdown": active})
    except ConnectionError as exc:
        return _err(str(exc), "PLC_ERROR", 503)
    except Exception as exc:
        logger.exception("set_lockdown")
        return _err(str(exc), "SERVER_ERROR", 500)
