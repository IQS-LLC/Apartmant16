import pyads
import time
from typing import Dict, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# DALI Constants
DALI_MAX_LEVEL = 254
DALI_MIN_LEVEL = 0
DALI_MAX_SCENE = 15
DALI_FADE_TIME_DEFAULT = 0.05  # seconds

PLC_AMS_ID = "192.168.0.161.1.1"
PLC_IP = "192.168.0.161"
NUM_DIMMERS = 16  # Updated based on project analysis; PLC currently has 2, but project suggests 16

class DALIController:
    """Controller for DALI dimmers via TwinCAT PLC using PyADS."""

    def __init__(self, ams_id: str = PLC_AMS_ID, ip: str = PLC_IP, num_dimmers: int = NUM_DIMMERS, fade_time: float = DALI_FADE_TIME_DEFAULT):
        self.ams_id = ams_id
        self.ip = ip
        self.num_dimmers = num_dimmers
        self.fade_time = fade_time
        self.plc: Optional[pyads.Connection] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to PLC."""
        return self._connected and self.plc is not None

    def connect(self) -> None:
        """Establish connection to the PLC."""
        if self.is_connected:
            logger.warning("Already connected to PLC")
            return

        try:
            self.plc = pyads.Connection(self.ams_id, pyads.PORT_TC3PLC1, self.ip)
            self.plc.open()
            self._connected = True
            logger.info(f"Connected to PLC at {self.ip}")
        except pyads.ADSError as e:
            self._connected = False
            logger.error(f"Failed to connect to PLC: {e}")
            raise

    def disconnect(self) -> None:
        """Close the connection to the PLC."""
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

    def __str__(self) -> str:
        return f"DALIController(ams_id={self.ams_id}, ip={self.ip}, dimmers={self.num_dimmers}, connected={self.is_connected})"

    def _validate_address(self, address: int) -> None:
        """Validate dimmer address."""
        if not (1 <= address <= self.num_dimmers):
            raise ValueError(f"Address must be between 1 and {self.num_dimmers}")

    def _validate_level(self, level: int) -> None:
        """Validate dimmer level."""
        if not (DALI_MIN_LEVEL <= level <= DALI_MAX_LEVEL):
            raise ValueError(f"Level must be between {DALI_MIN_LEVEL} and {DALI_MAX_LEVEL}")

    def _validate_scene(self, scene: int) -> None:
        """Validate scene number."""
        if not (0 <= scene <= DALI_MAX_SCENE):
            raise ValueError(f"Scene must be between 0 and {DALI_MAX_SCENE}")

    def _ensure_connected(self) -> None:
        """Ensure connection to PLC."""
        if not self.is_connected:
            raise RuntimeError("Not connected to PLC. Call connect() first.")

    def _pulse_bool(self, var_name: str) -> None:
        """Pulse a boolean variable (set True, wait, set False)."""
        self.plc.write_by_name(var_name, True, pyads.PLCTYPE_BOOL)
        time.sleep(self.fade_time)
        self.plc.write_by_name(var_name, False, pyads.PLCTYPE_BOOL)

    def set_dimmer_level(self, address: int, level: int) -> None:
        """Set the dimmer level for a specific address.

        Args:
            address: Dimmer address (1-16)
            level: Level value (0-254)
        """
        self._validate_address(address)
        self._validate_level(level)
        self._ensure_connected()

        try:
            self.plc.write_by_name(f"GVL_DALI_PyADS.aPyLevel[{address}]", level, pyads.PLCTYPE_BYTE)
            self._pulse_bool(f"GVL_DALI_PyADS.aPySetLevel[{address}]")
            logger.info(f"Set dimmer {address} to level {level}")
        except pyads.ADSError as e:
            logger.error(f"Failed to set dimmer level: {e}")
            raise

    def read_actual_level(self, address: int) -> int:
        """Read the actual level of a dimmer.

        Args:
            address: Dimmer address (1-16)

        Returns:
            Actual level (0-254)
        """
        self._validate_address(address)
        self._ensure_connected()

        try:
            level = self.plc.read_by_name(f"GVL_DALI_PyADS.aPyActualLevel[{address}]", pyads.PLCTYPE_BYTE)
            return level
        except pyads.ADSError as e:
            logger.error(f"Failed to read actual level: {e}")
            raise

    def read_all_levels(self) -> Dict[int, int]:
        """Read actual levels for all dimmers.

        Returns:
            Dictionary mapping address to level
        """
        return {i: self.read_actual_level(i) for i in range(1, self.num_dimmers + 1)}

    def set_all_to_level(self, level: int) -> None:
        """Set all dimmers to the same level.

        Args:
            level: Level value (0-254)
        """
        self._validate_level(level)
        self._ensure_connected()

        try:
            for addr in range(1, self.num_dimmers + 1):
                self.plc.write_by_name(f"GVL_DALI_PyADS.aPyLevel[{addr}]", level, pyads.PLCTYPE_BYTE)
                self._pulse_bool(f"GVL_DALI_PyADS.aPySetLevel[{addr}]")
            logger.info(f"Set all dimmers to level {level}")
        except pyads.ADSError as e:
            logger.error(f"Failed to set all dimmers: {e}")
            raise

    def toggle_dimmer(self, address: int) -> None:
        """Toggle the state of a dimmer.

        Args:
            address: Dimmer address (1-16)
        """
        self._validate_address(address)
        self._ensure_connected()

        try:
            self._pulse_bool(f"GVL_DALI_PyADS.aPyToggle[{address}]")
            logger.info(f"Toggled dimmer {address}")
        except pyads.ADSError as e:
            logger.error(f"Failed to toggle dimmer: {e}")
            raise

    def go_to_scene(self, address: int, scene: int) -> None:
        """Send dimmer to a specific scene.

        Args:
            address: Dimmer address (1-16)
            scene: Scene number (0-15)
        """
        self._validate_address(address)
        self._validate_scene(scene)
        self._ensure_connected()

        try:
            self.plc.write_by_name(f"GVL_DALI_PyADS.aPyScene[{address}]", scene, pyads.PLCTYPE_BYTE)
            self._pulse_bool(f"GVL_DALI_PyADS.aPyGoToScene[{address}]")
            logger.info(f"Set dimmer {address} to scene {scene}")
        except pyads.ADSError as e:
            logger.error(f"Failed to go to scene: {e}")
            raise

    def recall_max_level(self, address: int) -> None:
        """Recall maximum level for dimmer.

        Args:
            address: Dimmer address (1-16)
        """
        self._validate_address(address)
        self._ensure_connected()

        try:
            self._pulse_bool(f"GVL_DALI_PyADS.aPyRecallMax[{address}]")
            logger.info(f"Recalled max level for dimmer {address}")
        except pyads.ADSError as e:
            logger.error(f"Failed to recall max level: {e}")
            raise

    def recall_min_level(self, address: int) -> None:
        """Recall minimum level for dimmer.

        Args:
            address: Dimmer address (1-16)
        """
        self._validate_address(address)
        self._ensure_connected()

        try:
            self._pulse_bool(f"GVL_DALI_PyADS.aPyRecallMin[{address}]")
            logger.info(f"Recalled min level for dimmer {address}")
        except pyads.ADSError as e:
            logger.error(f"Failed to recall min level: {e}")
            raise

    def read_button_light_on(self) -> bool:
        """Read the button light on status.

        Returns:
            True if button indicates light on
        """
        self._ensure_connected()

        try:
            return self.plc.read_by_name("gvlDALI.gButtonLightOn", pyads.PLCTYPE_BOOL)
        except pyads.ADSError as e:
            logger.error(f"Failed to read button light on: {e}")
            raise

    def read_motion_light_on(self) -> bool:
        """Read the motion sensor light on status.

        Returns:
            True if motion sensor indicates light on
        """
        self._ensure_connected()

        try:
            return self.plc.read_by_name("gvlDALI.gMotionLightOn", pyads.PLCTYPE_BOOL)
        except pyads.ADSError as e:
            logger.error(f"Failed to read motion light on: {e}")
            raise

    def set_multiple_levels(self, levels: Dict[int, int]) -> None:
        """Set levels for multiple dimmers at once.

        Args:
            levels: Dictionary mapping address to level
        """
        for address, level in levels.items():
            self.set_dimmer_level(address, level)

    def get_system_status(self) -> Dict:
        """Get comprehensive system status for the web interface.

        Returns:
            Dictionary with all dimmer levels, button status, motion status
        """
        try:
            levels = self.read_all_levels()
            button_on = self.read_button_light_on()
            motion_on = self.read_motion_light_on()
            return {
                "dimmers": levels,
                "button_light_on": button_on,
                "motion_light_on": motion_on,
                "timestamp": time.time(),
                "num_dimmers": self.num_dimmers,
                "connected": self.is_connected
            }
        except Exception as e:
            logger.error(f"Failed to get system status: {e}")
            return {"error": str(e), "connected": self.is_connected}

    def emergency_all_off(self) -> None:
        """Set all dimmers to minimum level (emergency off)."""
        self.set_all_to_level(DALI_MIN_LEVEL)
        logger.info("Emergency all off executed")

    def scene_all(self, scene: int) -> None:
        """Set all dimmers to a specific scene.

        Args:
            scene: Scene number (0-15)
        """
        self._validate_scene(scene)
        self._ensure_connected()

        try:
            for addr in range(1, self.num_dimmers + 1):
                self.plc.write_by_name(f"GVL_DALI_PyADS.aPyScene[{addr}]", scene, pyads.PLCTYPE_BYTE)
                self._pulse_bool(f"GVL_DALI_PyADS.aPyGoToScene[{addr}]")
            logger.info(f"Set all dimmers to scene {scene}")
        except pyads.ADSError as e:
            logger.error(f"Failed to set all to scene: {e}")
            raise

    def get_plc_info(self) -> Dict:
        """Get basic PLC information.

        Returns:
            Dictionary with PLC info
        """
        self._ensure_connected()

        try:
            # Try to read some system info
            info = {
                "ams_id": self.ams_id,
                "ip": self.ip,
                "connected": True
            }
            # Could add more PLC-specific info if available
            return info
        except Exception as e:
            logger.error(f"Failed to get PLC info: {e}")
            return {"error": str(e), "connected": self.is_connected}

# Legacy functions for backward compatibility
def connect():
    plc = pyads.Connection(PLC_AMS_ID, pyads.PORT_TC3PLC1, PLC_IP)
    plc.open()
    return plc

def set_dimmer_level(plc, address: int, level: int):
    """address: 1-16, level: 0-254"""
    assert 1 <= address <= NUM_DIMMERS
    assert 0 <= level <= 254
    plc.write_by_name(f"GVL_DALI_PyADS.aPyLevel[{address}]", level, pyads.PLCTYPE_BYTE)
    plc.write_by_name(f"GVL_DALI_PyADS.aPySetLevel[{address}]", True, pyads.PLCTYPE_BOOL)
    time.sleep(0.05)
    plc.write_by_name(f"GVL_DALI_PyADS.aPySetLevel[{address}]", False, pyads.PLCTYPE_BOOL)

def read_actual_level(plc, address: int) -> int:
    assert 1 <= address <= NUM_DIMMERS
    return plc.read_by_name(f"GVL_DALI_PyADS.aPyActualLevel[{address}]", pyads.PLCTYPE_BYTE)

def read_all_levels(plc) -> dict:
    return {
        i: read_actual_level(plc, i)
        for i in range(1, NUM_DIMMERS + 1)
    }

# ── Example usage ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with DALIController() as controller:
        controller.set_dimmer_level(1, 128)  # dimmer 1 → 50%
        controller.set_dimmer_level(3, 254)  # dimmer 3 → max
        print(controller.read_all_levels())
        print(f"Button light on: {controller.read_button_light_on()}")
        print(f"Motion light on: {controller.read_motion_light_on()}")

def set_wall_relay(self, relay: int, state: bool) -> None:
    self._ensure_connected()
    self.plc.write_by_name(f"gvlDALI.aPyWallRelay[{relay}]", state, pyads.PLCTYPE_BOOL)

def read_wall_relay_state(self, relay: int) -> bool:
    self._ensure_connected()
    return self.plc.read_by_name(f"gvlDALI.aPyWallRelayState[{relay}]", pyads.PLCTYPE_BOOL)