"""
PLC device abstractions built on top of ADSClient.

Variable map — gvlDALI (DALI + relays + switches):
  DALI dimmers (channel 1-16):
    gvlDALI.aPyLevel[N]        BYTE   0-254   Python→PLC  desired level
    gvlDALI.aPySetLevel[N]     BOOL            Python→PLC  rising edge commits
    gvlDALI.aPyActualLevel[N]  BYTE   0-254   PLC→Python  confirmed readback

  Wall relays (channel 1-16; Apt 16 uses channels 1-5):
    gvlDALI.aPyWallRelay[N]      BOOL          Python→PLC  command
    gvlDALI.aPyWallRelayState[N] BOOL          PLC→Python  readback

  BTicino switches (index 1-48):
    gvlDALI.aPySwitchState[N]    BOOL          PLC→Python  live button state

Variable map — gvlIO (all other devices):
  Curtain motors (index 1-16):
    gvlIO.aPyCurtainCmd[N]     BYTE  0=stop 1=up 2=down   Python→PLC
    gvlIO.aPyCurtainState[N]   BYTE  0/1/2                PLC→Python readback

  Appliances (named):
    gvlIO.bPyFridgeCmd / bPyFridgeState
    gvlIO.bPyCoffeeMachineCmd / bPyCoffeeMachineState
    gvlIO.bPyMicrowaveCmd / bPyMicrowaveState

  Magnetic sensors:
    gvlIO.aPyDoorSensor[N]     BOOL  TRUE=open (index 1-16)
    gvlIO.aPyWindowSensor[N]   BOOL  TRUE=open (index 1-16)

  PIR/motion sensors (index 1-8):
    gvlIO.aPyMotionSensor[N]   BOOL  TRUE=motion detected

  Security:
    gvlIO.bPyKeySwitch         BOOL  PLC→Python  key switch physical state
    gvlIO.bPyAlarmArm          BOOL  Python→PLC  arm command
    gvlIO.bPyLockdown          BOOL  Python→PLC  lockdown command
    gvlIO.bPyAlarmState        BOOL  PLC→Python  armed state
    gvlIO.bPyAlarmTriggered    BOOL  PLC→Python  intrusion latched
    gvlIO.bPyLockdownState     BOOL  PLC→Python  lockdown active

Protocol for setting a DALI channel:
  1. write aPyLevel[N]    = target (0-254)
  2. write aPySetLevel[N] = True   (rising edge → PLC captures level)
  3. sleep ~50 ms
  4. write aPySetLevel[N] = False  (reset for next command)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import pyads

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def pct_to_byte(pct: int) -> int:
    return int(max(0, min(100, pct)) / 100 * 254)

def byte_to_pct(b: int) -> int:
    return round(max(0, min(254, b)) / 254 * 100)


# ── DaliChannel ───────────────────────────────────────────────────────────────

class DaliChannel:
    """Single Tridonic DALI dimmer channel (address 1-16)."""

    def __init__(self, channel: int, name: str, room: str, client):
        if not 1 <= channel <= 16:
            raise ValueError(f"DALI channel must be 1-16, got {channel}")
        self.channel = channel
        self.name    = name
        self.room    = room
        self._client = client
        self._mock_level = 0

    @property
    def _var_level(self)     -> str: return f'gvlDALI.aPyLevel[{self.channel}]'
    @property
    def _var_set_level(self) -> str: return f'gvlDALI.aPySetLevel[{self.channel}]'
    @property
    def _var_actual(self)    -> str: return f'gvlDALI.aPyActualLevel[{self.channel}]'

    def set_brightness(self, percent: int):
        level = pct_to_byte(percent)
        if self._client.mock:
            self._mock_level = level
            return
        self._client.write(self._var_level,     level, pyads.PLCTYPE_BYTE)
        self._client.write(self._var_set_level, True,  pyads.PLCTYPE_BOOL)
        time.sleep(0.05)
        self._client.write(self._var_set_level, False, pyads.PLCTYPE_BOOL)

    def read_actual_level(self) -> int:
        if self._client.mock:
            return byte_to_pct(self._mock_level)
        return byte_to_pct(int(self._client.read(self._var_actual, pyads.PLCTYPE_BYTE)))

    def to_dict(self) -> Dict[str, Any]:
        return {'channel': self.channel, 'name': self.name, 'room': self.room,
                'device_type': 'dali_light'}


# ── WallRelay ─────────────────────────────────────────────────────────────────

class WallRelay:
    """
    Relay-driven wall light (channel 1-16; Apt 16 uses 1-5).

    Maps to gvlDALI.aPyWallRelay[N] / aPyWallRelayState[N].
    """

    def __init__(self, channel: int, name: str, room: str, client):
        if not 1 <= channel <= 16:
            raise ValueError(f"WallRelay channel must be 1-16, got {channel}")
        self.channel = channel
        self.name    = name
        self.room    = room
        self._client = client
        self._mock_state = False

    @property
    def _var_cmd(self)   -> str: return f'gvlDALI.aPyWallRelay[{self.channel}]'
    @property
    def _var_state(self) -> str: return f'gvlDALI.aPyWallRelayState[{self.channel}]'

    def set_state(self, on: bool):
        if self._client.mock:
            self._mock_state = on
            return
        self._client.write(self._var_cmd, on, pyads.PLCTYPE_BOOL)

    def read_state(self) -> bool:
        if self._client.mock:
            return self._mock_state
        return bool(self._client.read(self._var_state, pyads.PLCTYPE_BOOL))

    def to_dict(self) -> Dict[str, Any]:
        return {'channel': self.channel, 'name': self.name, 'room': self.room,
                'device_type': 'wall_relay'}


# ── SwitchInput ───────────────────────────────────────────────────────────────

class SwitchInput:
    """BTicino L4036 push-button input (index 1-48, KL1809 terminals)."""

    def __init__(self, index: int, name: str, room: str, client):
        if not 1 <= index <= 48:
            raise ValueError(f"Switch index must be 1-48, got {index}")
        self.index   = index
        self.name    = name
        self.room    = room
        self._client = client
        self._mock_state = False

    @property
    def _var(self) -> str: return f'gvlDALI.aPySwitchState[{self.index}]'

    def read_state(self) -> bool:
        if self._client.mock:
            return self._mock_state
        return bool(self._client.read(self._var, pyads.PLCTYPE_BOOL))

    def to_dict(self) -> Dict[str, Any]:
        return {'index': self.index, 'name': self.name, 'room': self.room,
                'device_type': 'switch_input'}


# ── CurtainMotor ──────────────────────────────────────────────────────────────

class CurtainMotor:
    """
    Curtain/blind motor (index 1-16).

    Commands : 0 = stop,  1 = up (raise),  2 = down (lower)
    State     : mirrors command after PLC safety interlock resolves it.
    """

    STOP = 0
    UP   = 1
    DOWN = 2

    def __init__(self, index: int, name: str, room: str, client):
        if not 1 <= index <= 16:
            raise ValueError(f"CurtainMotor index must be 1-16, got {index}")
        self.index   = index
        self.name    = name
        self.room    = room
        self._client = client
        self._mock_state = 0   # 0/1/2

    @property
    def _var_cmd(self)   -> str: return f'gvlIO.aPyCurtainCmd[{self.index}]'
    @property
    def _var_state(self) -> str: return f'gvlIO.aPyCurtainState[{self.index}]'

    def set_command(self, cmd: int):
        """Send stop (0), up (1), or down (2)."""
        if cmd not in (self.STOP, self.UP, self.DOWN):
            raise ValueError(f"Curtain cmd must be 0/1/2, got {cmd}")
        if self._client.mock:
            self._mock_state = cmd
            return
        self._client.write(self._var_cmd, cmd, pyads.PLCTYPE_BYTE)

    def read_state(self) -> int:
        if self._client.mock:
            return self._mock_state
        return int(self._client.read(self._var_state, pyads.PLCTYPE_BYTE))

    def to_dict(self) -> Dict[str, Any]:
        return {'index': self.index, 'name': self.name, 'room': self.room,
                'device_type': 'curtain_motor'}


# ── ApplianceRelay ────────────────────────────────────────────────────────────

# Canonical appliance names understood by both PLC GVL and this class
APPLIANCE_NAMES = ('Fridge', 'CoffeeMachine', 'Microwave')

class ApplianceRelay:
    """
    Smart appliance controlled by a relay (fridge, coffee machine, microwave).

    gvl_name must be one of: 'Fridge', 'CoffeeMachine', 'Microwave'
    Maps to gvlIO.bPy{gvl_name}Cmd / bPy{gvl_name}State
    """

    def __init__(self, gvl_name: str, display_name: str, room: str, client):
        if gvl_name not in APPLIANCE_NAMES:
            raise ValueError(f"gvl_name must be one of {APPLIANCE_NAMES}, got {gvl_name!r}")
        self.gvl_name     = gvl_name
        self.name         = display_name
        self.room         = room
        self._client      = client
        self._mock_state  = False

    @property
    def _var_cmd(self)   -> str: return f'gvlIO.bPy{self.gvl_name}Cmd'
    @property
    def _var_state(self) -> str: return f'gvlIO.bPy{self.gvl_name}State'

    def set_state(self, on: bool):
        if self._client.mock:
            self._mock_state = on
            return
        self._client.write(self._var_cmd, on, pyads.PLCTYPE_BOOL)

    def read_state(self) -> bool:
        if self._client.mock:
            return self._mock_state
        return bool(self._client.read(self._var_state, pyads.PLCTYPE_BOOL))

    def to_dict(self) -> Dict[str, Any]:
        return {'gvl_name': self.gvl_name, 'name': self.name, 'room': self.room,
                'device_type': 'appliance'}


# ── MagneticSensor ────────────────────────────────────────────────────────────

class MagneticSensor:
    """
    Door or window magnetic contact sensor (index 1-16).

    sensor_type: 'door' or 'window'
    Maps to gvlIO.aPyDoorSensor[N] or gvlIO.aPyWindowSensor[N]
    TRUE = open (contact broken).
    """

    def __init__(self, index: int, sensor_type: str, name: str, room: str, client):
        if not 1 <= index <= 16:
            raise ValueError(f"MagneticSensor index must be 1-16, got {index}")
        if sensor_type not in ('door', 'window'):
            raise ValueError(f"sensor_type must be 'door' or 'window', got {sensor_type!r}")
        self.index       = index
        self.sensor_type = sensor_type
        self.name        = name
        self.room        = room
        self._client     = client
        self._mock_state = False

    @property
    def _var(self) -> str:
        prefix = 'Door' if self.sensor_type == 'door' else 'Window'
        return f'gvlIO.aPy{prefix}Sensor[{self.index}]'

    def read_state(self) -> bool:
        """Returns True if the door/window is open."""
        if self._client.mock:
            return self._mock_state
        return bool(self._client.read(self._var, pyads.PLCTYPE_BOOL))

    def to_dict(self) -> Dict[str, Any]:
        return {'index': self.index, 'sensor_type': self.sensor_type,
                'name': self.name, 'room': self.room,
                'device_type': 'magnetic_sensor'}


# ── MotionSensor ──────────────────────────────────────────────────────────────

class MotionSensor:
    """PIR / presence sensor (index 1-8). Maps to gvlIO.aPyMotionSensor[N]."""

    def __init__(self, index: int, name: str, room: str, client):
        if not 1 <= index <= 8:
            raise ValueError(f"MotionSensor index must be 1-8, got {index}")
        self.index   = index
        self.name    = name
        self.room    = room
        self._client = client
        self._mock_state = False

    @property
    def _var(self) -> str: return f'gvlIO.aPyMotionSensor[{self.index}]'

    def read_state(self) -> bool:
        if self._client.mock:
            return self._mock_state
        return bool(self._client.read(self._var, pyads.PLCTYPE_BOOL))

    def to_dict(self) -> Dict[str, Any]:
        return {'index': self.index, 'name': self.name, 'room': self.room,
                'device_type': 'motion_sensor'}


# ── SecurityController ────────────────────────────────────────────────────────

class SecurityController:
    """
    Alarm and lockdown controller (one per apartment).

    Writes:  bPyAlarmArm, bPyLockdown
    Reads:   bPyAlarmState, bPyAlarmTriggered, bPyLockdownState, bPyKeySwitch
    """

    def __init__(self, client):
        self._client = client
        self._mock = {'armed': False, 'triggered': False, 'lockdown': False, 'key': False}

    # ── Commands ──────────────────────────────────────────────────────────────

    def set_alarm_armed(self, armed: bool):
        if self._client.mock:
            self._mock['armed'] = armed
            return
        self._client.write('gvlIO.bPyAlarmArm', armed, pyads.PLCTYPE_BOOL)

    def set_lockdown(self, active: bool):
        if self._client.mock:
            self._mock['lockdown'] = active
            return
        self._client.write('gvlIO.bPyLockdown', active, pyads.PLCTYPE_BOOL)

    # ── State reads ───────────────────────────────────────────────────────────

    def read_alarm_state(self) -> bool:
        if self._client.mock:
            return self._mock['armed']
        return bool(self._client.read('gvlIO.bPyAlarmState', pyads.PLCTYPE_BOOL))

    def read_alarm_triggered(self) -> bool:
        if self._client.mock:
            return self._mock['triggered']
        return bool(self._client.read('gvlIO.bPyAlarmTriggered', pyads.PLCTYPE_BOOL))

    def read_lockdown_state(self) -> bool:
        if self._client.mock:
            return self._mock['lockdown']
        return bool(self._client.read('gvlIO.bPyLockdownState', pyads.PLCTYPE_BOOL))

    def read_key_switch(self) -> bool:
        if self._client.mock:
            return self._mock['key']
        return bool(self._client.read('gvlIO.bPyKeySwitch', pyads.PLCTYPE_BOOL))

    def read_full_state(self) -> dict:
        return {
            'armed':     self.read_alarm_state(),
            'triggered': self.read_alarm_triggered(),
            'lockdown':  self.read_lockdown_state(),
            'key_switch': self.read_key_switch(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {'device_type': 'security_controller'}
