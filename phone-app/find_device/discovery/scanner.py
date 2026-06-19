"""
Lumina ADS Symbol Scanner — enumerate TwinCAT 3 symbols via PyADS.

In real mode:  connects to ADS, reads the symbol upload info, then streams
               all symbol entries and returns raw dicts.
In mock mode:  returns a realistic sample symbol list that exercises all
               widget types the classifier can produce.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("lumina.discovery")


# ─────────────────────────────────────────────────────────────────────────────
# Mock symbol table  (used when ADS is unavailable or PLC_MOCK=True)
# ─────────────────────────────────────────────────────────────────────────────

_MOCK_SYMBOLS: list[dict] = [
    # ── DALI Lighting ─────────────────────────────────────────────────────────
    {"full_name": "gvlDALI.nBrightness_1",  "type_name": "INT",  "comment": "Living Room Main"},
    {"full_name": "gvlDALI.nBrightness_2",  "type_name": "INT",  "comment": "Living Room Accent"},
    {"full_name": "gvlDALI.nBrightness_3",  "type_name": "INT",  "comment": "Dining Room"},
    {"full_name": "gvlDALI.nBrightness_4",  "type_name": "INT",  "comment": "Kitchen"},
    {"full_name": "gvlDALI.nBrightness_5",  "type_name": "INT",  "comment": "Bedroom 1"},
    {"full_name": "gvlDALI.nBrightness_6",  "type_name": "INT",  "comment": "Bedroom 2"},
    {"full_name": "gvlDALI.nBrightness_7",  "type_name": "INT",  "comment": "Hallway"},
    {"full_name": "gvlDALI.nBrightness_8",  "type_name": "INT",  "comment": "Office"},
    {"full_name": "gvlDALI.nScene",         "type_name": "INT",  "comment": "Active Scene"},

    # ── Relays ────────────────────────────────────────────────────────────────
    {"full_name": "gvlRelays.bState_ExtLight",  "type_name": "BOOL", "comment": "Exterior Light"},
    {"full_name": "gvlRelays.bState_GarageGate","type_name": "BOOL", "comment": "Garage Gate"},
    {"full_name": "gvlRelays.bState_Fountain",  "type_name": "BOOL", "comment": "Garden Fountain"},
    {"full_name": "gvlRelays.bState_Boiler",    "type_name": "BOOL", "comment": "Hot Water Boiler"},

    # ── HVAC ──────────────────────────────────────────────────────────────────
    {"full_name": "gvlHVAC.fSetpoint_LivingRoom", "type_name": "REAL", "comment": "Living Room Target Temp"},
    {"full_name": "gvlHVAC.fActualTemp_LivingRoom","type_name": "REAL", "comment": "Living Room Temperature"},
    {"full_name": "gvlHVAC.fSetpoint_Bedroom",    "type_name": "REAL", "comment": "Bedroom Target Temp"},
    {"full_name": "gvlHVAC.fActualTemp_Bedroom",  "type_name": "REAL", "comment": "Bedroom Temperature"},
    {"full_name": "gvlHVAC.nMode",                "type_name": "INT",  "comment": "HVAC Mode (0=Off 1=Heat 2=Cool 3=Auto 4=Fan)"},
    {"full_name": "gvlHVAC.nFanSpeed",            "type_name": "INT",  "comment": "Fan Speed %"},
    {"full_name": "gvlHVAC.fHumidity",            "type_name": "REAL", "comment": "Indoor Humidity"},

    # ── Alarms ────────────────────────────────────────────────────────────────
    {"full_name": "gvlAlarms.bAlarm_Smoke",   "type_name": "BOOL", "comment": "Smoke Detector"},
    {"full_name": "gvlAlarms.bAlarm_Flood",   "type_name": "BOOL", "comment": "Flood Sensor"},
    {"full_name": "gvlAlarms.bAlarm_Intruder","type_name": "BOOL", "comment": "Motion / Intrusion"},
    {"full_name": "gvlAlarms.bFault_HVAC",    "type_name": "BOOL", "comment": "HVAC System Fault"},

    # ── Energy monitoring ─────────────────────────────────────────────────────
    {"full_name": "gvlEnergy.fPower_Total",   "type_name": "REAL", "comment": "Total Power Draw"},
    {"full_name": "gvlEnergy.fEnergy_Today",  "type_name": "REAL", "comment": "Energy Today"},

    # ── Sensors ───────────────────────────────────────────────────────────────
    {"full_name": "gvlSensor.fTemp_Outdoor", "type_name": "REAL", "comment": "Outdoor Temperature"},
    {"full_name": "gvlSensor.fHumid_Outdoor","type_name": "REAL", "comment": "Outdoor Humidity"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────────────

class SymbolScanner:
    """
    Scans TwinCAT 3 ADS symbols for a given device.

    Usage:
        scanner = SymbolScanner(ip="192.168.0.158", ams_net_id="192.168.0.158.1.1",
                                ads_port=851, mock=False)
        raw_symbols, duration_ms = scanner.scan()
    """

    def __init__(
        self,
        ip:         str,
        ams_net_id: str,
        ads_port:   int  = 851,
        mock:       bool = True,
        timeout_s:  float = 10.0,
    ):
        self.ip         = ip
        self.ams_net_id = ams_net_id
        self.ads_port   = ads_port
        self.mock       = mock
        self.timeout_s  = timeout_s

    def scan(self) -> tuple[list[dict], int]:
        """
        Returns (raw_symbol_list, duration_ms).

        raw_symbol_list elements:
          {full_name, type_name, comment, index_group, index_offset}
        """
        start = time.monotonic()
        if self.mock:
            symbols = list(_MOCK_SYMBOLS)
        else:
            symbols = self._scan_real()
        ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Symbol scan complete: %d symbols in %dms  mock=%s",
            len(symbols), ms, self.mock,
        )
        return symbols, ms

    def _scan_real(self) -> list[dict]:
        """
        Enumerate all ADS symbols via pyads upload-info + symbol-by-index.

        Returns a flat list of symbol dicts.  We only return symbols whose
        full name contains a dot (i.e. they live under a GVL / FB), and skip
        system / TwinCAT internal prefixes.
        """
        try:
            import pyads  # type: ignore
        except ImportError:
            logger.warning("pyads not installed — falling back to mock data")
            return list(_MOCK_SYMBOLS)

        _SKIP_PREFIXES = (
            "TwinCAT_SystemInfoVarList", "Constants", "TaskCycleCounter",
            "PlcTask", "_TaskInfo", "SYSTEMINFO",
        )

        plc = pyads.Connection(self.ams_net_id, self.ads_port, self.ip)
        symbols: list[dict] = []
        try:
            plc.open()
            all_syms = plc.get_all_symbols()
            for sym in all_syms:
                name = sym.name or ""
                if "." not in name:
                    continue
                if any(name.startswith(pfx) for pfx in _SKIP_PREFIXES):
                    continue
                symbols.append({
                    "full_name":    name,
                    "type_name":    sym.symbol_type or "UNKNOWN",
                    "comment":      getattr(sym, "comment", "") or "",
                    "index_group":  getattr(sym, "index_group", 0),
                    "index_offset": getattr(sym, "index_offset", 0),
                })
        except Exception as exc:
            logger.error("ADS symbol scan failed: %s", exc)
            raise ConnectionError(f"ADS symbol scan failed: {exc}") from exc
        finally:
            try:
                plc.close()
            except Exception:
                pass

        return symbols
