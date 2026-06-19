"""
DeviceRegistry — singleton that owns the ADSClient and all device objects.

Multi-apartment design
──────────────────────
All apartment-specific data lives in the APARTMENT_CONFIGS dict at the bottom
of this file.  To add a new apartment:

  1.  Add an entry to APARTMENT_CONFIGS keyed by the apartment ID (e.g. 17).
  2.  Each entry is a plain dict with keys:
        dali, relays, curtains, switches, door_sensors, window_sensors,
        motion_sensors, appliances
      Each value is a list of kwargs dicts matching the device constructors
      in devices.py.
  3.  If using multiple Django instances (one per apartment) just change
      the APARTMENT_ID env var; the registry self-configures at startup.
  4.  If running a single multi-tenant Django: instantiate DeviceRegistry
      for each apartment ID (they each hold a separate ADSClient + connection).

The registry reads the default PLCDevice from the DB (manage/devices/) so
the ADS connection address can be changed without touching source code.
PLC_MOCK=True in env always wins (safe for dev/CI).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

from .ads_client import ADSClient
from .devices import (
    DaliChannel, WallRelay, SwitchInput,
    CurtainMotor, ApplianceRelay,
    MagneticSensor, MotionSensor, SecurityController,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  APARTMENT CONFIGS
#  ─────────────────
#  Add one entry per apartment.  Only the layout changes; Python driver code,
#  GVL variable names, and array sizes are identical across all apartments.
# ═══════════════════════════════════════════════════════════════════════════════

APARTMENT_CONFIGS: dict[int, dict] = {

    # ── Apartment 16 ────────────────────────────────────────────────────────
    16: dict(
        dali=[
            # channel, name, room
            dict(channel=1,  name='Light 1',  room='Living Room'),
            dict(channel=2,  name='Light 2',  room='Living Room'),
            dict(channel=3,  name='Light 3',  room='Living Room'),
            dict(channel=4,  name='Light 4',  room='Living Room'),
            dict(channel=5,  name='Light 5',  room='Dining Room'),
            dict(channel=6,  name='Light 6',  room='Dining Room'),
            dict(channel=7,  name='Light 7',  room='Dining Room'),
            dict(channel=8,  name='Light 8',  room='Dining Room'),
            dict(channel=9,  name='Light 9',  room='Bedroom 1'),
            dict(channel=10, name='Light 10', room='Bedroom 1'),
            dict(channel=11, name='Light 11', room='Bedroom 2'),
            dict(channel=12, name='Light 12', room='Bedroom 2'),
            dict(channel=13, name='Light 13', room='Kitchen'),
            dict(channel=14, name='Light 14', room='Kitchen'),
            dict(channel=15, name='Light 15', room='Hallway'),
            dict(channel=16, name='Light 16', room='Hallway'),
        ],
        relays=[
            # channel, name, room
            dict(channel=1, name='Wall Light 1', room='Living Room'),
            dict(channel=2, name='Wall Light 2', room='Living Room'),
            dict(channel=3, name='Wall Light 3', room='Hallway'),
            dict(channel=4, name='Wall Light 4', room='Hallway'),
            dict(channel=5, name='Wall Light 5', room='Kitchen'),
        ],
        curtains=[
            # index, name, room
            dict(index=1, name='Curtain 1', room='Living Room'),
            dict(index=2, name='Curtain 2', room='Living Room'),
            dict(index=3, name='Curtain 3', room='Dining Room'),
            dict(index=4, name='Curtain 4', room='Dining Room'),
            dict(index=5, name='Curtain 5', room='Bedroom 1'),
            dict(index=6, name='Curtain 6', room='Bedroom 2'),
            dict(index=7, name='Curtain 7', room='Kitchen'),
            dict(index=8, name='Curtain 8', room='Hallway'),
        ],
        switches=[
            # index, name, room  — physical BTicino buttons
            dict(index=1,  name='Living Room Main',  room='Living Room'),
            dict(index=2,  name='Dining Room Main',  room='Dining Room'),
            dict(index=3,  name='Bedroom 1 Main',    room='Bedroom 1'),
            dict(index=4,  name='Bedroom 2 Main',    room='Bedroom 2'),
            dict(index=5,  name='Kitchen Main',      room='Kitchen'),
            dict(index=6,  name='Hallway Main',      room='Hallway'),
            dict(index=7,  name='Wall Light 1 SW',   room='Living Room'),
            dict(index=8,  name='Wall Light 2 SW',   room='Living Room'),
            dict(index=9,  name='Wall Light 3 SW',   room='Hallway'),
            dict(index=10, name='Wall Light 4 SW',   room='Hallway'),
            dict(index=11, name='Wall Light 5 SW',   room='Kitchen'),
            dict(index=12, name='Curtain 1 Up',      room='Living Room'),
            dict(index=13, name='Curtain 1 Down',    room='Living Room'),
            dict(index=14, name='Curtain 2 Up',      room='Living Room'),
            dict(index=15, name='Curtain 2 Down',    room='Living Room'),
            dict(index=16, name='Curtain 3 Up',      room='Dining Room'),
            dict(index=17, name='Curtain 3 Down',    room='Dining Room'),
            dict(index=18, name='Curtain 4 Up',      room='Dining Room'),
            dict(index=19, name='Curtain 4 Down',    room='Dining Room'),
            dict(index=20, name='Curtain 5 Up',      room='Bedroom 1'),
            dict(index=21, name='Curtain 5 Down',    room='Bedroom 1'),
            dict(index=22, name='Curtain 6 Up',      room='Bedroom 2'),
            dict(index=23, name='Curtain 6 Down',    room='Bedroom 2'),
            dict(index=24, name='Curtain 7 Up',      room='Kitchen'),
            dict(index=25, name='Curtain 7 Down',    room='Kitchen'),
            dict(index=26, name='Curtain 8 Up',      room='Hallway'),
            dict(index=27, name='Curtain 8 Down',    room='Hallway'),
        ],
        door_sensors=[
            # index, name, room
            dict(index=1, name='Front Door',    room='Entrance'),
            dict(index=2, name='Back Door',     room='Entrance'),
            dict(index=3, name='Balcony Door',  room='Living Room'),
        ],
        window_sensors=[
            dict(index=1, name='Living Room Window 1', room='Living Room'),
            dict(index=2, name='Living Room Window 2', room='Living Room'),
            dict(index=3, name='Bedroom 1 Window',     room='Bedroom 1'),
            dict(index=4, name='Bedroom 2 Window',     room='Bedroom 2'),
            dict(index=5, name='Kitchen Window',       room='Kitchen'),
        ],
        motion_sensors=[
            dict(index=1, name='Motion Living Room', room='Living Room'),
            dict(index=2, name='Motion Hallway',     room='Hallway'),
            dict(index=3, name='Motion Bedroom 1',   room='Bedroom 1'),
            dict(index=4, name='Motion Dining Room', room='Dining Room'),
        ],
        appliances=[
            # gvl_name, display_name, room
            dict(gvl_name='Fridge',        display_name='Fridge',         room='Kitchen'),
            dict(gvl_name='CoffeeMachine', display_name='Coffee Machine', room='Kitchen'),
            dict(gvl_name='Microwave',     display_name='Microwave',      room='Kitchen'),
        ],
    ),

    # ── Template for future apartments ──────────────────────────────────────
    # Copy the block above, increment key, adjust names/counts.
    # The Python driver, GVL variable names and array sizes stay identical.
}


# ═══════════════════════════════════════════════════════════════════════════════
#  DeviceRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class DeviceRegistry:
    """
    Central registry for all PLC devices in one apartment.

    Thread-safe singleton per process.  For multi-apartment in a single
    process, call DeviceRegistry.for_apartment(apt_id) to get apartment-
    scoped instances instead of using the global singleton.
    """

    _instance:      Optional['DeviceRegistry'] = None
    _instance_lock  = threading.Lock()

    # Per-apartment instances (for multi-tenant use)
    _apt_instances: Dict[int, 'DeviceRegistry'] = {}
    _apt_lock       = threading.Lock()

    def __init__(self, apartment_id: int = 16):
        self.apartment_id = apartment_id
        mock = os.getenv('PLC_MOCK', 'True').lower() == 'true'
        self._client = ADSClient(
            netid=os.getenv('PLC_NETID', '5.168.214.75.1.1'),
            ip   =os.getenv('PLC_IP',    '192.168.0.161'),
            mock =mock,
        )
        self._dali:           Dict[int, DaliChannel]      = {}
        self._relays:         Dict[int, WallRelay]        = {}
        self._switches:       Dict[int, SwitchInput]      = {}
        self._curtains:       Dict[int, CurtainMotor]     = {}
        self._appliances:     Dict[str, ApplianceRelay]   = {}
        self._door_sensors:   Dict[int, MagneticSensor]  = {}
        self._window_sensors: Dict[int, MagneticSensor]  = {}
        self._motion_sensors: Dict[int, MotionSensor]    = {}
        self._security:       Optional[SecurityController] = None
        self._lock    = threading.RLock()
        self._started = False

    # ── Startup ───────────────────────────────────────────────────────────────

    def _start(self):
        if self._started:
            return

        # Override ADS connection from DB if a default PLCDevice is configured.
        # PLC_MOCK=True in env always wins (safe for dev/CI).
        if not self._client.mock:
            try:
                from django.apps import apps
                PLCDevice = apps.get_model('find_device', 'PLCDevice')
                device = PLCDevice.objects.filter(
                    is_default=True, is_active=True,
                ).first()
                if device:
                    self._client.netid = device.ams_net_id
                    self._client.ip    = device.ip_address
                    logger.info(
                        "DeviceRegistry[apt%d]: using PLCDevice '%s' (%s @ %s)",
                        self.apartment_id, device.name,
                        device.ams_net_id, device.ip_address,
                    )
            except Exception as exc:
                logger.debug(
                    "DeviceRegistry[apt%d]: no PLCDevice in DB, using env vars: %s",
                    self.apartment_id, exc,
                )

        ok = self._client.connect()
        if not ok and not self._client.mock:
            logger.warning(
                "DeviceRegistry[apt%d]: PLC unreachable — falling back to mock",
                self.apartment_id,
            )
            self._client.mock = True
            self._client.connect()

        cfg = APARTMENT_CONFIGS.get(self.apartment_id, {})
        for d in cfg.get('dali', []):
            self.add_dali(**d)
        for r in cfg.get('relays', []):
            self.add_relay(**r)
        for c in cfg.get('curtains', []):
            self.add_curtain(**c)
        for s in cfg.get('switches', []):
            self.add_switch(**s)
        for ds in cfg.get('door_sensors', []):
            self.add_door_sensor(**ds)
        for ws in cfg.get('window_sensors', []):
            self.add_window_sensor(**ws)
        for ms in cfg.get('motion_sensors', []):
            self.add_motion_sensor(**ms)
        for ap in cfg.get('appliances', []):
            self.add_appliance(**ap)
        self._security = SecurityController(self._client)

        self._started = True
        logger.info(
            "DeviceRegistry[apt%d] ready: %d DALI, %d relays, %d curtains, "
            "%d switches, %d door, %d window, %d motion, %d appliances  mock=%s",
            self.apartment_id,
            len(self._dali), len(self._relays), len(self._curtains),
            len(self._switches), len(self._door_sensors),
            len(self._window_sensors), len(self._motion_sensors),
            len(self._appliances), self._client.mock,
        )

    # ── Registration helpers ──────────────────────────────────────────────────

    def add_dali(self, channel: int, name: str, room: str):
        with self._lock:
            self._dali[channel] = DaliChannel(channel, name, room, self._client)

    def add_relay(self, channel: int, name: str, room: str):
        with self._lock:
            self._relays[channel] = WallRelay(channel, name, room, self._client)

    def add_curtain(self, index: int, name: str, room: str):
        with self._lock:
            self._curtains[index] = CurtainMotor(index, name, room, self._client)

    def add_switch(self, index: int, name: str, room: str):
        with self._lock:
            self._switches[index] = SwitchInput(index, name, room, self._client)

    def add_door_sensor(self, index: int, name: str, room: str):
        with self._lock:
            self._door_sensors[index] = MagneticSensor(
                index, 'door', name, room, self._client)

    def add_window_sensor(self, index: int, name: str, room: str):
        with self._lock:
            self._window_sensors[index] = MagneticSensor(
                index, 'window', name, room, self._client)

    def add_motion_sensor(self, index: int, name: str, room: str):
        with self._lock:
            self._motion_sensors[index] = MotionSensor(
                index, name, room, self._client)

    def add_appliance(self, gvl_name: str, display_name: str, room: str):
        with self._lock:
            self._appliances[gvl_name] = ApplianceRelay(
                gvl_name, display_name, room, self._client)

    # ── Accessors ─────────────────────────────────────────────────────────────

    def dali(self, channel: int)       -> Optional[DaliChannel]:      return self._dali.get(channel)
    def relay(self, channel: int)      -> Optional[WallRelay]:        return self._relays.get(channel)
    def curtain(self, index: int)      -> Optional[CurtainMotor]:     return self._curtains.get(index)
    def switch(self, index: int)       -> Optional[SwitchInput]:      return self._switches.get(index)
    def appliance(self, gvl_name: str) -> Optional[ApplianceRelay]:  return self._appliances.get(gvl_name)
    def door_sensor(self, index: int)  -> Optional[MagneticSensor]:  return self._door_sensors.get(index)
    def window_sensor(self, index: int)-> Optional[MagneticSensor]:  return self._window_sensors.get(index)
    def motion_sensor(self, index: int)-> Optional[MotionSensor]:    return self._motion_sensors.get(index)

    def security(self)            -> Optional[SecurityController]: return self._security
    def all_dali(self)            -> List[DaliChannel]:     return list(self._dali.values())
    def all_relays(self)          -> List[WallRelay]:       return list(self._relays.values())
    def all_curtains(self)        -> List[CurtainMotor]:    return list(self._curtains.values())
    def all_switches(self)        -> List[SwitchInput]:     return list(self._switches.values())
    def all_appliances(self)      -> List[ApplianceRelay]:  return list(self._appliances.values())
    def all_door_sensors(self)    -> List[MagneticSensor]:  return list(self._door_sensors.values())
    def all_window_sensors(self)  -> List[MagneticSensor]:  return list(self._window_sensors.values())
    def all_motion_sensors(self)  -> List[MotionSensor]:    return list(self._motion_sensors.values())

    def rooms(self) -> List[str]:
        seen, result = set(), []
        for d in (*self._dali.values(), *self._relays.values(), *self._curtains.values()):
            if d.room not in seen:
                seen.add(d.room)
                result.append(d.room)
        return result

    @property
    def mock(self)      -> bool: return self._client.mock
    @property
    def connected(self) -> bool: return self._client.is_connected

    # ── Full state read (hot path — called every 2 s by Flutter poll) ─────────

    def read_full_state(self) -> dict:
        dali_levels, relay_states, curtain_states = {}, {}, {}
        switch_states, appliance_states = {}, {}
        door_states, window_states, motion_states = {}, {}, {}

        for ch, dev in self._dali.items():
            try:
                dali_levels[ch] = dev.read_actual_level()
            except Exception as exc:
                logger.error("DALI ch%d read: %s", ch, exc)
                dali_levels[ch] = None

        for ch, dev in self._relays.items():
            try:
                relay_states[ch] = dev.read_state()
            except Exception as exc:
                logger.error("Relay ch%d read: %s", ch, exc)
                relay_states[ch] = None

        for idx, dev in self._curtains.items():
            try:
                curtain_states[idx] = dev.read_state()
            except Exception as exc:
                logger.error("Curtain %d read: %s", idx, exc)
                curtain_states[idx] = None

        for idx, dev in self._switches.items():
            try:
                switch_states[idx] = dev.read_state()
            except Exception as exc:
                logger.error("Switch %d read: %s", idx, exc)
                switch_states[idx] = None

        for idx, dev in self._door_sensors.items():
            try:
                door_states[idx] = dev.read_state()
            except Exception as exc:
                logger.error("Door sensor %d read: %s", idx, exc)
                door_states[idx] = None

        for idx, dev in self._window_sensors.items():
            try:
                window_states[idx] = dev.read_state()
            except Exception as exc:
                logger.error("Window sensor %d read: %s", idx, exc)
                window_states[idx] = None

        for idx, dev in self._motion_sensors.items():
            try:
                motion_states[idx] = dev.read_state()
            except Exception as exc:
                logger.error("Motion sensor %d read: %s", idx, exc)
                motion_states[idx] = None

        for name, dev in self._appliances.items():
            try:
                appliance_states[name] = dev.read_state()
            except Exception as exc:
                logger.error("Appliance %s read: %s", name, exc)
                appliance_states[name] = None

        security_state = {}
        if self._security:
            try:
                security_state = self._security.read_full_state()
            except Exception as exc:
                logger.error("Security read: %s", exc)

        return {
            'mock':        self._client.mock,
            'apartment_id': self.apartment_id,
            'dali':        dali_levels,
            'relays':      relay_states,
            'curtains':    curtain_states,
            'switches':    switch_states,
            'door_sensors':   door_states,
            'window_sensors': window_states,
            'motion_sensors': motion_states,
            'appliances':  appliance_states,
            'security':    security_state,
        }

    # ── Singleton (default apartment = env var APARTMENT_ID, default 16) ──────

    @classmethod
    def instance(cls) -> 'DeviceRegistry':
        with cls._instance_lock:
            if cls._instance is None:
                apt_id = int(os.getenv('APARTMENT_ID', '16'))
                inst = cls(apartment_id=apt_id)
                inst._start()
                cls._instance = inst
            return cls._instance

    @classmethod
    def for_apartment(cls, apt_id: int) -> 'DeviceRegistry':
        """Return (or create) the registry for a specific apartment ID."""
        with cls._apt_lock:
            if apt_id not in cls._apt_instances:
                inst = cls(apartment_id=apt_id)
                inst._start()
                cls._apt_instances[apt_id] = inst
            return cls._apt_instances[apt_id]
