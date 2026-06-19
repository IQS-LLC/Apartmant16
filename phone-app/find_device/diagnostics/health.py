"""
Lumina Health Monitor — tracks ADS connection health across all registered PLCDevices.

Provides:
  - Per-device health snapshots
  - ADS state polling
  - Error rate tracking
  - Uptime tracking
  - Connection event log (last 100 events)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("lumina.health")

# ADS state code → human-readable name
_ADS_STATE_NAMES: dict[int, str] = {
    0:  "INVALID",
    1:  "IDLE",
    2:  "RESET",
    3:  "INIT",
    4:  "START",
    5:  "RUN",
    6:  "STOP",
    7:  "SAVECFG",
    8:  "LOADCFG",
    9:  "POWERFAILURE",
    10: "POWERGOOD",
    11: "ERROR",
    12: "SHUTDOWN",
    13: "SUSPEND",
    14: "RESUME",
    15: "CONFIG",
    16: "RECONFIG",
    17: "STOPPING",
}


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DeviceHealthSnapshot:
    """Point-in-time health record for one PLC device."""

    ams_net_id:      str
    ip_address:      str
    device_name:     str   = ""
    ads_state:       str   = "UNKNOWN"
    ads_state_code:  int   = -1
    device_state:    int   = 0
    connected:       bool  = False
    mock:            bool  = False
    uptime_s:        float = 0.0
    read_count:      int   = 0
    write_count:     int   = 0
    error_count:     int   = 0
    error_rate:      float = 0.0        # errors / total ops
    avg_latency_ms:  float = 0.0
    last_error:      Optional[str] = None
    last_checked:    float = field(default_factory=time.monotonic)
    last_seen:       Optional[float] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (monotonic timestamps converted to wall-clock offset)."""
        now = time.monotonic()
        return {
            "ams_net_id":     self.ams_net_id,
            "ip_address":     self.ip_address,
            "device_name":    self.device_name,
            "ads_state":      self.ads_state,
            "ads_state_code": self.ads_state_code,
            "device_state":   self.device_state,
            "connected":      self.connected,
            "mock":           self.mock,
            "uptime_s":       round(self.uptime_s, 1),
            "read_count":     self.read_count,
            "write_count":    self.write_count,
            "error_count":    self.error_count,
            "error_rate":     round(self.error_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_error":     self.last_error,
            # seconds ago (None → null)
            "last_checked_s_ago": round(now - self.last_checked, 1),
            "last_seen_s_ago": (
                round(now - self.last_seen, 1) if self.last_seen is not None else None
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# HealthMonitor singleton
# ─────────────────────────────────────────────────────────────────────────────

class HealthMonitor:
    """
    Singleton that periodically checks ADS state for all active connections.

    Usage:
        monitor = HealthMonitor.instance()
        monitor.start(interval_s=30)
        snapshot = monitor.get_snapshot("192.168.0.158.1.1")
    """

    _instance:      Optional['HealthMonitor'] = None
    _instance_lock: threading.Lock            = threading.Lock()

    @classmethod
    def instance(cls) -> 'HealthMonitor':
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._device_health: dict[str, DeviceHealthSnapshot] = {}
        self._event_log:     deque = deque(maxlen=100)
        self._monitor_thread: Optional[threading.Thread] = None
        self._running:        bool = False
        self._lock:           threading.RLock = threading.RLock()
        # Track when each device connection was first established (monotonic)
        self._connect_time:   dict[str, float] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, interval_s: float = 30.0) -> None:
        """Start a background daemon thread that polls all devices every interval_s."""
        with self._lock:
            if self._running:
                return
            self._running = True

        def _loop():
            logger.info("HealthMonitor started (interval=%.0fs)", interval_s)
            while self._running:
                try:
                    self._check_all()
                except Exception:
                    logger.exception("HealthMonitor: unexpected error in _check_all")
                # Sleep in small increments so stop() is responsive
                deadline = time.monotonic() + interval_s
                while self._running and time.monotonic() < deadline:
                    time.sleep(0.5)
            logger.info("HealthMonitor stopped")

        self._monitor_thread = threading.Thread(
            target=_loop, name="lumina-health-monitor", daemon=True
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        """Signal the monitor thread to stop and wait for it to exit."""
        self._running = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

    # ── Core poll ─────────────────────────────────────────────────────────────

    def _check_all(self) -> None:
        """Import DeviceRegistry and probe every registered device."""
        try:
            from find_device.plc.registry import DeviceRegistry  # lazy import avoids circular deps
        except ImportError:
            logger.warning("HealthMonitor: could not import DeviceRegistry")
            return

        try:
            registry = DeviceRegistry.instance()
        except Exception as exc:
            logger.error("HealthMonitor: failed to get DeviceRegistry: %s", exc)
            return

        # The registry exposes its internal ADSClient; iterate over known
        # device configurations to build per-netid snapshots.
        client      = registry._client
        ams_net_id  = client.netid
        ip_address  = client.ip

        self._check_device(client, ams_net_id, ip_address)

    def _check_device(self, client, ams_net_id: str, ip: str) -> None:
        """
        Probe a single ADSClient and update _device_health for ams_net_id.

        Reads:
          - client.is_connected / client.mock   → connected / mock flags
          - client._conn.read_state()           → ads_state, device_state (if available)
          - pyads device_info                   → device_name, version
        """
        now        = time.monotonic()
        is_mock    = getattr(client, "mock", True)
        connected  = getattr(client, "is_connected", False)

        # Existing snapshot (for cumulative counters)
        with self._lock:
            prev = self._device_health.get(ams_net_id)

        ads_state_code = -1
        ads_state_name = "UNKNOWN"
        device_state   = 0
        device_name    = prev.device_name if prev else ""
        avg_latency_ms = prev.avg_latency_ms if prev else 0.0
        error_count    = prev.error_count if prev else 0
        read_count     = prev.read_count if prev else 0
        last_error     = prev.last_error if prev else None
        last_seen      = prev.last_seen if prev else None

        # Track uptime from first successful connection
        if connected and not is_mock:
            if ams_net_id not in self._connect_time:
                self._connect_time[ams_net_id] = now
            uptime_s = now - self._connect_time[ams_net_id]
            last_seen = now
        else:
            # Reset connect_time when disconnected so uptime restarts after reconnect
            self._connect_time.pop(ams_net_id, None)
            uptime_s = 0.0

        # Try to read live ADS state (non-mock only)
        if connected and not is_mock:
            try:
                t0 = time.monotonic()
                conn = getattr(client, "_conn", None)
                if conn is not None:
                    state_tuple = conn.read_state()  # returns (ads_state, device_state)
                    if state_tuple and len(state_tuple) >= 2:
                        ads_state_code = int(state_tuple[0])
                        device_state   = int(state_tuple[1])
                        ads_state_name = _ADS_STATE_NAMES.get(ads_state_code, f"STATE_{ads_state_code}")
                latency = (time.monotonic() - t0) * 1000
                # Rolling average (weight last reading 20%)
                avg_latency_ms = avg_latency_ms * 0.8 + latency * 0.2 if avg_latency_ms else latency
                read_count += 1
            except Exception as exc:
                error_count += 1
                last_error = str(exc)
                logger.debug("HealthMonitor: read_state failed for %s: %s", ams_net_id, exc)

            # Try to get device info (name / version)
            try:
                conn = getattr(client, "_conn", None)
                if conn is not None:
                    info = conn.get_device_info()
                    if info:
                        device_name = getattr(info, "name", device_name) or device_name
            except Exception:
                pass  # non-fatal — device_name stays as-is

        elif is_mock:
            ads_state_code = 5   # RUN
            ads_state_name = "RUN"
            device_name    = device_name or "Mock PLC"
            uptime_s       = (now - self._connect_time.setdefault(ams_net_id, now))

        # Compute error rate
        total_ops   = read_count + error_count
        error_rate  = error_count / total_ops if total_ops > 0 else 0.0

        snapshot = DeviceHealthSnapshot(
            ams_net_id     = ams_net_id,
            ip_address     = ip,
            device_name    = device_name,
            ads_state      = ads_state_name,
            ads_state_code = ads_state_code,
            device_state   = device_state,
            connected      = connected or is_mock,
            mock           = is_mock,
            uptime_s       = uptime_s,
            read_count     = read_count,
            write_count    = prev.write_count if prev else 0,
            error_count    = error_count,
            error_rate     = error_rate,
            avg_latency_ms = avg_latency_ms,
            last_error     = last_error,
            last_checked   = now,
            last_seen      = last_seen,
        )

        with self._lock:
            self._device_health[ams_net_id] = snapshot

        event_type = "connected" if snapshot.connected else "disconnected"
        if prev is None or prev.connected != snapshot.connected:
            self.log_event(
                ams_net_id,
                event_type,
                f"Device {ams_net_id} is now {event_type} (ads_state={ads_state_name})",
            )

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_snapshot(self, ams_net_id: str) -> Optional[DeviceHealthSnapshot]:
        """Return the latest health snapshot for the given AMS Net ID, or None."""
        with self._lock:
            return self._device_health.get(ams_net_id)

    def get_all_snapshots(self) -> list[DeviceHealthSnapshot]:
        """Return a list of all known device health snapshots."""
        with self._lock:
            return list(self._device_health.values())

    # ── Event log ─────────────────────────────────────────────────────────────

    def log_event(self, ams_net_id: str, event_type: str, message: str) -> None:
        """
        Append a connection event to the rolling log (capped at 100 entries).

        Args:
            ams_net_id: AMS Net ID of the device.
            event_type: e.g. "connected", "disconnected", "error", "state_change".
            message:    Human-readable description.
        """
        entry = {
            "ts":         time.time(),
            "ams_net_id": ams_net_id,
            "type":       event_type,
            "message":    message,
        }
        with self._lock:
            self._event_log.append(entry)

    def get_event_log(
        self,
        ams_net_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Return recent events, most-recent first.

        Args:
            ams_net_id: If given, filter to events for that device only.
            limit:      Maximum number of events to return (1-100).
        """
        limit = max(1, min(100, limit))
        with self._lock:
            events = list(self._event_log)   # oldest-first copy

        if ams_net_id:
            events = [e for e in events if e.get("ams_net_id") == ams_net_id]

        # Return most-recent first
        return list(reversed(events))[:limit]

    # ── Summary property ──────────────────────────────────────────────────────

    @property
    def summary(self) -> dict:
        """
        High-level aggregation across all tracked devices.

        Returns:
            {
              "total_devices":   int,
              "connected_count": int,
              "error_count":     int,     # total cumulative errors across all devices
              "avg_latency_ms":  float,   # mean of per-device avg latencies
            }
        """
        snapshots = self.get_all_snapshots()
        connected_count = sum(1 for s in snapshots if s.connected)
        total_errors    = sum(s.error_count for s in snapshots)
        latencies       = [s.avg_latency_ms for s in snapshots if s.avg_latency_ms > 0]
        avg_latency     = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            "total_devices":   len(snapshots),
            "connected_count": connected_count,
            "error_count":     total_errors,
            "avg_latency_ms":  round(avg_latency, 2),
        }
