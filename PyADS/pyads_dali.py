import pyads
import time

PLC_AMS_ID  = "192.168.0.161.1.1"
PLC_IP      = "192.168.0.161"
NUM_DIMMERS = 16

def connect():
    plc = pyads.Connection(PLC_AMS_ID, pyads.PORT_TC3PLC1, PLC_IP)
    plc.open()
    return plc

def set_dimmer_level(plc, address: int, level: int):
    """address: 1-16, level: 0-254"""
    assert 1 <= address <= NUM_DIMMERS
    assert 0 <= level <= 254
    plc.write_by_name(f"GVL_DALI_PyADS.aPyLevel[{address}]",   level, pyads.PLCTYPE_BYTE)
    plc.write_by_name(f"GVL_DALI_PyADS.aPySetLevel[{address}]", True,  pyads.PLCTYPE_BOOL)
    time.sleep(0.05)  # give PLC one scan cycle to latch the rising edge
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
    plc = connect()
    set_dimmer_level(plc, 1, 128)   # dimmer 1 → 50%
    set_dimmer_level(plc, 3, 254)   # dimmer 3 → max
    print(read_all_levels(plc))
    plc.close()