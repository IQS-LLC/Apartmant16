import pyads
import time
from typing import Dict, List, Optional, Tuple
import logging

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── DALI Constants ────────────────────────────────────────────────────────────
DALI_MAX_LEVEL      = 254
DALI_MIN_LEVEL      = 0
DALI_MAX_SCENE      = 15
DALI_NUM_DIMMERS    = 16
DALI_NUM_RELAYS     = 4
PULSE_DELAY         = 0.05   # seconds — one PLC scan cycle margin

# ── PLC Connection ────────────────────────────────────────────────────────────
PLC_AMS_ID  = "192.168.0.161.1.1"
PLC_IP      = "192.168.0.161"

# ── GVL Symbol Paths ─────────────────────────────────────────────────────────
# All symbols live in gvlDALI — matches the actual TwinCAT GVL name
GVL = "gvlDALI"


class DALIController:
    """
    DALI lighting controller for Apartment 16 — IQS Lugh system.
    Communicates with TwinCAT PLC via PyADS over ADS protocol.

    GVL requirements (gvlDALI):
        aPyLevel            : ARRAY[1..16] OF BYTE       — desired level per dimmer
        aPySetLevel         : ARRAY[1..16] OF BOOL       — rising edge triggers set
        aPyActualLevel      : ARRAY[1..16] OF BYTE       — actual level readback
        aPyToggle           : ARRAY[1..16] OF BOOL       — rising edge toggles dimmer
        aPyRecallMax        : ARRAY[1..16] OF BOOL       — rising edge recalls max
        aPyRecallMin        : ARRAY[1..16] OF BOOL       — rising edge recalls min
        aPyScene            : ARRAY[1..16] OF BYTE       — scene number per dimmer
        aPyGoToScene        : ARRAY[1..16] OF BOOL       — rising edge goes to scene
        aPyWallRelay        : ARRAY[1..4]  OF BOOL       — wall relay commands (app)
        aPyWallRelayState   : ARRAY[1..4]  OF BOOL       — wall relay state readback
        gButtonLightOn      : BOOL                       — physical button state
        gMotionLightOn      : BOOL                       — motion sensor state
    """

    def __init__(
        self,
        ams_id:      str   = PLC_AMS_ID,
        ip:          str   = PLC_IP,
        num_dimmers: int   = DALI_NUM_DIMMERS,
        num_relays:  int   = DALI_NUM_RELAYS,
        pulse_delay: float = PULSE_DELAY,
    ):
        self.ams_id      = ams_id
        self.ip          = ip
        self.num_dimmers = num_dimmers
        self.num_relays  = num_relays
        self.pulse_delay = pulse_delay
        self.plc: Optional[pyads.Connection] = None
        self._connected  = False

    # ── Connection ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected and self.plc is not None

    def connect(self) -> None:
        if self.is_connected:
            logger.warning("Already connected to PLC")
            return
        try:
            self.plc = pyads.Connection(self.ams_id, pyads.PORT_TC3PLC1, self.ip)
            self.plc.open()
            self._connected = True
            logger.info(f"Connected to PLC at {self.ip} ({self.ams_id})")
        except pyads.ADSError as e:
            self._connected = False
            logger.error(f"Failed to connect to PLC: {e}")
            raise

    def disconnect(self) -> None:
        if self.plc and self._connected:
            try:
                self.plc.close()
                logger.info("Disconnected from PLC")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self._connected = False
                self.plc = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def __repr__(self) -> str:
        return (
            f"DALIController(ip={self.ip}, ams_id={self.ams_id}, "
            f"dimmers={self.num_dimmers}, connected={self.is_connected})"
        )

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_address(self, address: int) -> None:
        if not (1 <= address <= self.num_dimmers):
            raise ValueError(f"Address must be 1–{self.num_dimmers}, got {address}")

    def _validate_level(self, level: int) -> None:
        if not (DALI_MIN_LEVEL <= level <= DALI_MAX_LEVEL):
            raise ValueError(f"Level must be {DALI_MIN_LEVEL}–{DALI_MAX_LEVEL}, got {level}")

    def _validate_scene(self, scene: int) -> None:
        if not (0 <= scene <= DALI_MAX_SCENE):
            raise ValueError(f"Scene must be 0–{DALI_MAX_SCENE}, got {scene}")

    def _validate_relay(self, relay: int) -> None:
        if not (1 <= relay <= self.num_relays):
            raise ValueError(f"Relay must be 1–{self.num_relays}, got {relay}")

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected to PLC. Call connect() first.")

    # ── Low-level ADS helpers ─────────────────────────────────────────────────

    def _write(self, symbol: str, value, plc_type) -> None:
        """Write a value to a PLC symbol."""
        self.plc.write_by_name(f"{GVL}.{symbol}", value, plc_type)

    def _read(self, symbol: str, plc_type):
        """Read a value from a PLC symbol."""
        return self.plc.read_by_name(f"{GVL}.{symbol}", plc_type)

    def _pulse(self, symbol: str) -> None:
        """Pulse a BOOL symbol TRUE → delay → FALSE (rising edge trigger)."""
        self._write(symbol, True,  pyads.PLCTYPE_BOOL)
        time.sleep(self.pulse_delay)
        self._write(symbol, False, pyads.PLCTYPE_BOOL)

    # ── DALI Dimmer Control ───────────────────────────────────────────────────

    def set_level(self, address: int, level: int) -> None:
        """Set a specific dimmer to an exact level (0–254)."""
        self._validate_address(address)
        self._validate_level(level)
        self._ensure_connected()
        try:
            self._write(f"aPyLevel[{address}]",    level, pyads.PLCTYPE_BYTE)
            self._pulse(f"aPySetLevel[{address}]")
            logger.info(f"Dimmer {address} → level {level}")
        except pyads.ADSError as e:
            logger.error(f"set_level({address}, {level}) failed: {e}")
            raise

    def toggle(self, address: int) -> None:
        """Toggle a dimmer on/off."""
        self._validate_address(address)
        self._ensure_connected()
        try:
            self._pulse(f"aPyToggle[{address}]")
            logger.info(f"Dimmer {address} toggled")
        except pyads.ADSError as e:
            logger.error(f"toggle({address}) failed: {e}")
            raise

    def recall_max(self, address: int) -> None:
        """Recall maximum level for a dimmer."""
        self._validate_address(address)
        self._ensure_connected()
        try:
            self._pulse(f"aPyRecallMax[{address}]")
            logger.info(f"Dimmer {address} → max level")
        except pyads.ADSError as e:
            logger.error(f"recall_max({address}) failed: {e}")
            raise

    def recall_min(self, address: int) -> None:
        """Recall minimum level for a dimmer."""
        self._validate_address(address)
        self._ensure_connected()
        try:
            self._pulse(f"aPyRecallMin[{address}]")
            logger.info(f"Dimmer {address} → min level")
        except pyads.ADSError as e:
            logger.error(f"recall_min({address}) failed: {e}")
            raise

    def go_to_scene(self, address: int, scene: int) -> None:
        """Send a dimmer to a specific scene (0–15)."""
        self._validate_address(address)
        self._validate_scene(scene)
        self._ensure_connected()
        try:
            self._write(f"aPyScene[{address}]",    scene, pyads.PLCTYPE_BYTE)
            self._pulse(f"aPyGoToScene[{address}]")
            logger.info(f"Dimmer {address} → scene {scene}")
        except pyads.ADSError as e:
            logger.error(f"go_to_scene({address}, {scene}) failed: {e}")
            raise

    def read_level(self, address: int) -> int:
        """Read the actual level of a dimmer."""
        self._validate_address(address)
        self._ensure_connected()
        try:
            return self._read(f"aPyActualLevel[{address}]", pyads.PLCTYPE_BYTE)
        except pyads.ADSError as e:
            logger.error(f"read_level({address}) failed: {e}")
            raise

    # ── Multi-dimmer Operations ───────────────────────────────────────────────

    def read_all_levels(self) -> Dict[int, int]:
        """Read actual levels for all dimmers. Returns {address: level}."""
        self._ensure_connected()
        return {i: self.read_level(i) for i in range(1, self.num_dimmers + 1)}

    def set_multiple_levels(self, levels: Dict[int, int]) -> None:
        """Set levels for multiple dimmers. levels = {address: level}."""
        for address, level in levels.items():
            self.set_level(address, level)

    def set_all_levels(self, level: int) -> None:
        """Set all dimmers to the same level."""
        self._validate_level(level)
        self._ensure_connected()
        for addr in range(1, self.num_dimmers + 1):
            self._write(f"aPyLevel[{addr}]",    level, pyads.PLCTYPE_BYTE)
            self._pulse(f"aPySetLevel[{addr}]")
        logger.info(f"All dimmers → level {level}")

    def all_off(self) -> None:
        """Turn all dimmers off (level 0)."""
        self.set_all_levels(DALI_MIN_LEVEL)
        logger.info("All dimmers OFF")

    def all_max(self) -> None:
        """Set all dimmers to maximum level."""
        self.set_all_levels(DALI_MAX_LEVEL)
        logger.info("All dimmers MAX")

    def scene_all(self, scene: int) -> None:
        """Send all dimmers to the same scene."""
        self._validate_scene(scene)
        self._ensure_connected()
        for addr in range(1, self.num_dimmers + 1):
            self._write(f"aPyScene[{addr}]",    scene, pyads.PLCTYPE_BYTE)
            self._pulse(f"aPyGoToScene[{addr}]")
        logger.info(f"All dimmers → scene {scene}")

    def set_group_level(self, addresses: List[int], level: int) -> None:
        """Set a specific group of dimmers to the same level."""
        self._validate_level(level)
        for address in addresses:
            self._validate_address(address)
        self._ensure_connected()
        for address in addresses:
            self._write(f"aPyLevel[{address}]",    level, pyads.PLCTYPE_BYTE)
            self._pulse(f"aPySetLevel[{address}]")
        logger.info(f"Group {addresses} → level {level}")

    # ── Wall Relay Control ────────────────────────────────────────────────────

    def set_relay(self, relay: int, state: bool) -> None:
        """Set a wall relay on or off."""
        self._validate_relay(relay)
        self._ensure_connected()
        try:
            self._write(f"aPyWallRelay[{relay}]", state, pyads.PLCTYPE_BOOL)
            logger.info(f"Relay {relay} → {'ON' if state else 'OFF'}")
        except pyads.ADSError as e:
            logger.error(f"set_relay({relay}, {state}) failed: {e}")
            raise

    def read_relay_state(self, relay: int) -> bool:
        """Read the current state of a wall relay."""
        self._validate_relay(relay)
        self._ensure_connected()
        try:
            return self._read(f"aPyWallRelayState[{relay}]", pyads.PLCTYPE_BOOL)
        except pyads.ADSError as e:
            logger.error(f"read_relay_state({relay}) failed: {e}")
            raise

    def read_all_relay_states(self) -> Dict[int, bool]:
        """Read states of all wall relays. Returns {relay: state}."""
        self._ensure_connected()
        return {i: self.read_relay_state(i) for i in range(1, self.num_relays + 1)}

    # ── Physical Inputs ───────────────────────────────────────────────────────

    def read_button_state(self) -> bool:
        """Read the physical button light-on state."""
        self._ensure_connected()
        try:
            return self._read("gButtonLightOn", pyads.PLCTYPE_BOOL)
        except pyads.ADSError as e:
            logger.error(f"read_button_state() failed: {e}")
            raise

    def read_motion_state(self) -> bool:
        """Read the motion sensor state."""
        self._ensure_connected()
        try:
            return self._read("gMotionLightOn", pyads.PLCTYPE_BOOL)
        except pyads.ADSError as e:
            logger.error(f"read_motion_state() failed: {e}")
            raise

    # ── System Status (Django backend ready) ──────────────────────────────────

    def get_status(self) -> Dict:
        """
        Full system snapshot — use this as the Django API status endpoint response.
        Returns all dimmer levels, relay states, and physical inputs in one call.
        """
        self._ensure_connected()
        try:
            return {
                "connected":    True,
                "timestamp":    time.time(),
                "dimmers":      self.read_all_levels(),
                "relays":       self.read_all_relay_states(),
                "button_on":    self.read_button_state(),
                "motion_on":    self.read_motion_state(),
                "num_dimmers":  self.num_dimmers,
                "num_relays":   self.num_relays,
            }
        except Exception as e:
            logger.error(f"get_status() failed: {e}")
            return {
                "connected": self.is_connected,
                "error":     str(e),
                "timestamp": time.time(),
            }

    def get_plc_info(self) -> Dict:
        """Basic PLC connection info — useful for Django health-check endpoint."""
        return {
            "ams_id":       self.ams_id,
            "ip":           self.ip,
            "connected":    self.is_connected,
            "num_dimmers":  self.num_dimmers,
            "num_relays":   self.num_relays,
        }


# ── Example usage ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with DALIController() as ctrl:
        print(ctrl.get_plc_info())

        ctrl.set_level(1, 128)          # dimmer 1 → 50%
        ctrl.set_level(3, 254)          # dimmer 3 → max
        ctrl.set_group_level([4,5,6], 180)  # group of three
        ctrl.set_relay(1, True)         # wall relay 1 ON

        print(ctrl.get_status())