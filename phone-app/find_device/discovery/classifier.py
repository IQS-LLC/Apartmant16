"""
Lumina Symbol Classifier — maps TwinCAT ADS symbols to Lumina widget types.

Philosophy
──────────────────────────────────────────────────────────────────────────────
The classifier works in layers:

  1. GVL prefix  — identifies the functional area (HVAC, DALI, alarms, …)
  2. Variable name tokens — pattern matching on common naming conventions
  3. ADS type    — the raw data type (BOOL, INT, REAL, STRING, …)
  4. Fallback    — always produces a usable display widget

Widget types produced
─────────────────────
  dali_slider     → DALI brightness, 0-100 %
  toggle          → Boolean on/off
  thermostat      → Temperature setpoint + read-back
  alarm_card      → Alarm / fault indicator
  mode_selector   → Multi-step mode (e.g. HVAC mode 0-4)
  numeric_display → Read-only integer / real
  text_display    → Read-only string
  gauge           → Percentage / bounded value
  unknown         → Raw value, shown as key=value
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Widget type identifiers (string constants used in JSON → Flutter maps these)
# ─────────────────────────────────────────────────────────────────────────────

WIDGET_DALI_SLIDER    = "dali_slider"
WIDGET_TOGGLE         = "toggle"
WIDGET_THERMOSTAT     = "thermostat"
WIDGET_ALARM_CARD     = "alarm_card"
WIDGET_MODE_SELECTOR  = "mode_selector"
WIDGET_NUMERIC        = "numeric_display"
WIDGET_TEXT           = "text_display"
WIDGET_GAUGE          = "gauge"
WIDGET_UNKNOWN        = "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# GVL category map — keyed on lower-case GVL prefix
# ─────────────────────────────────────────────────────────────────────────────

_GVL_CATEGORY: dict[str, str] = {
    "gvldali":    "lighting",
    "gvlhvac":   "hvac",
    "gvlalarms": "alarms",
    "gvlrelays": "relays",
    "gvlswitch": "switches",
    "gvlinput":  "inputs",
    "gvloutput": "outputs",
    "gvlsensor": "sensors",
    "gvlmotor":  "motors",
    "gvlpump":   "pumps",
    "gvlvalve":  "valves",
    "gvlenergy": "energy",
}

# ─────────────────────────────────────────────────────────────────────────────
# Name-token patterns
# ─────────────────────────────────────────────────────────────────────────────

# Alarm / fault patterns (highest priority — override type-based logic)
_ALARM_PATTERNS = re.compile(
    r"(alarm|fault|error|warning|trip|fail|emergency|e_stop|estop)",
    re.IGNORECASE,
)

# Temperature / HVAC
_TEMP_PATTERNS = re.compile(
    r"(temp(erature)?|setpoint|sp|actual_temp|room_temp|supply_temp|return_temp"
    r"|t_room|t_set|t_act|pv|sv)",
    re.IGNORECASE,
)

# Brightness / DALI
_DALI_PATTERNS = re.compile(
    r"(bright(ness)?|dimm|level|lumen|intensity|dim|dali)",
    re.IGNORECASE,
)

# Mode / scene selectors
_MODE_PATTERNS = re.compile(
    r"(mode|scene|state_machine|step|phase|program|sequence)",
    re.IGNORECASE,
)

# Percentage / gauge
_GAUGE_PATTERNS = re.compile(
    r"(percent|pct|pos(ition)?|opening|valve_pos|fan_speed|speed|rpm)",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# ADS type helpers
# ─────────────────────────────────────────────────────────────────────────────

_BOOL_TYPES  = frozenset({"BOOL"})
_INT_TYPES   = frozenset({"INT", "UINT", "DINT", "UDINT", "SINT", "USINT", "BYTE", "WORD", "DWORD"})
_REAL_TYPES  = frozenset({"REAL", "LREAL"})
_STR_TYPES   = frozenset({"STRING", "WSTRING"})


# ─────────────────────────────────────────────────────────────────────────────
# Symbol descriptor
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SymbolDescriptor:
    """Enriched symbol returned by the classifier."""

    full_name:   str            # e.g. "gvlDALI.nBrightness_1"
    gvl:         str            # e.g. "gvlDALI"
    name:        str            # e.g. "nBrightness_1"
    type_name:   str            # ADS type string, e.g. "INT"
    comment:     str = ""       # PLC inline comment
    category:    str = "other"  # derived from GVL
    widget_type: str = WIDGET_UNKNOWN

    # Widget hints — filled in by classifier
    label:       str = ""       # human-readable label
    unit:        str = ""       # e.g. "°C", "%", "W"
    min_value:   Optional[float] = None
    max_value:   Optional[float] = None
    read_only:   bool = False
    group:       str = ""       # e.g. room name or GVL

    # Raw ADS symbol index / handle — populated by scanner
    index_group:  int = 0
    index_offset: int = 0

    def to_dict(self) -> dict:
        return {
            "full_name":    self.full_name,
            "gvl":          self.gvl,
            "name":         self.name,
            "type_name":    self.type_name,
            "comment":      self.comment,
            "category":     self.category,
            "widget_type":  self.widget_type,
            "label":        self.label,
            "unit":         self.unit,
            "min_value":    self.min_value,
            "max_value":    self.max_value,
            "read_only":    self.read_only,
            "group":        self.group,
            "index_group":  self.index_group,
            "index_offset": self.index_offset,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify(
    full_name: str,
    type_name: str,
    comment:   str = "",
) -> SymbolDescriptor:
    """
    Classify a TwinCAT symbol and return an enriched SymbolDescriptor.

    full_name : dotted ADS path, e.g. "gvlDALI.nBrightness_1"
    type_name : ADS type string, e.g. "INT", "BOOL", "REAL"
    comment   : optional PLC inline comment
    """
    parts = full_name.split(".", 1)
    gvl   = parts[0] if len(parts) == 2 else ""
    name  = parts[1] if len(parts) == 2 else full_name

    category = _GVL_CATEGORY.get(gvl.lower(), "other")

    sym = SymbolDescriptor(
        full_name=full_name,
        gvl=gvl,
        name=name,
        type_name=type_name.upper(),
        comment=comment,
        category=category,
        group=gvl,
    )

    _assign_widget(sym)
    _assign_label(sym)
    _assign_unit(sym)
    _assign_range(sym)

    return sym


def _assign_widget(sym: SymbolDescriptor) -> None:
    """Assign widget_type based on category, name tokens, and ADS type."""
    t = sym.type_name
    n = sym.name

    # ── Alarms always win ────────────────────────────────────────────────────
    if sym.category == "alarms" or _ALARM_PATTERNS.search(n):
        sym.widget_type = WIDGET_ALARM_CARD
        sym.read_only   = True
        return

    # ── DALI lighting ────────────────────────────────────────────────────────
    if sym.category == "lighting" or _DALI_PATTERNS.search(n):
        if t in _INT_TYPES:
            sym.widget_type = WIDGET_DALI_SLIDER
            return
        if t in _BOOL_TYPES:
            sym.widget_type = WIDGET_TOGGLE
            return

    # ── HVAC / temperature ───────────────────────────────────────────────────
    if sym.category == "hvac" or _TEMP_PATTERNS.search(n):
        if t in _REAL_TYPES:
            sym.widget_type = WIDGET_THERMOSTAT
            return
        if t in _INT_TYPES and _MODE_PATTERNS.search(n):
            sym.widget_type = WIDGET_MODE_SELECTOR
            return

    # ── Mode / scene selector ────────────────────────────────────────────────
    if _MODE_PATTERNS.search(n) and t in _INT_TYPES:
        sym.widget_type = WIDGET_MODE_SELECTOR
        return

    # ── Gauges / percentages ─────────────────────────────────────────────────
    if _GAUGE_PATTERNS.search(n):
        sym.widget_type = WIDGET_GAUGE
        return

    # ── Boolean → toggle ─────────────────────────────────────────────────────
    if t in _BOOL_TYPES:
        sym.widget_type = WIDGET_TOGGLE
        return

    # ── String → text display ────────────────────────────────────────────────
    if t in _STR_TYPES:
        sym.widget_type = WIDGET_TEXT
        sym.read_only   = True
        return

    # ── Numeric catch-all ────────────────────────────────────────────────────
    if t in _INT_TYPES | _REAL_TYPES:
        sym.widget_type = WIDGET_NUMERIC
        sym.read_only   = True
        return

    sym.widget_type = WIDGET_UNKNOWN
    sym.read_only   = True


def _assign_label(sym: SymbolDescriptor) -> None:
    """Convert variable name token to a human-readable label."""
    # Use PLC comment if available
    if sym.comment:
        sym.label = sym.comment.strip()
        return

    # Strip Hungarian notation prefix (n, b, f, s, e, i + uppercase after)
    name = sym.name
    cleaned = re.sub(r"^[nbfseiwr](?=[A-Z])", "", name)

    # Split on camelCase, underscores, and digits
    tokens = re.sub(r"([A-Z])", r" \1", cleaned)
    tokens = re.sub(r"[_\-]", " ", tokens)
    tokens = re.sub(r"\s+", " ", tokens).strip()

    # Remove trailing channel numbers for cleaner labeling
    tokens = re.sub(r"\s+\d+$", "", tokens)

    sym.label = tokens.title() or sym.name


def _assign_unit(sym: SymbolDescriptor) -> None:
    """Infer measurement unit from name and widget type."""
    n = sym.name.lower()

    if sym.widget_type == WIDGET_DALI_SLIDER:
        sym.unit = "%"
    elif sym.widget_type == WIDGET_THERMOSTAT or _TEMP_PATTERNS.search(n):
        sym.unit = "°C"
    elif _GAUGE_PATTERNS.search(n) and "rpm" in n:
        sym.unit = "rpm"
    elif _GAUGE_PATTERNS.search(n) and "speed" in n:
        sym.unit = "%"
    elif "power" in n or "watt" in n:
        sym.unit = "W"
    elif "energy" in n or "kwh" in n:
        sym.unit = "kWh"
    elif "pressure" in n or "pa" in n:
        sym.unit = "Pa"
    elif "flow" in n:
        sym.unit = "L/s"
    elif "humid" in n:
        sym.unit = "%RH"


def _assign_range(sym: SymbolDescriptor) -> None:
    """Assign sensible default value ranges."""
    if sym.widget_type == WIDGET_DALI_SLIDER:
        sym.min_value, sym.max_value = 0.0, 100.0
    elif sym.widget_type == WIDGET_THERMOSTAT:
        sym.min_value, sym.max_value = 15.0, 30.0
    elif sym.widget_type == WIDGET_GAUGE and sym.unit == "%":
        sym.min_value, sym.max_value = 0.0, 100.0
    elif sym.widget_type == WIDGET_MODE_SELECTOR:
        sym.min_value, sym.max_value = 0.0, 4.0


# ─────────────────────────────────────────────────────────────────────────────
# Batch classify helper
# ─────────────────────────────────────────────────────────────────────────────

def classify_batch(
    raw_symbols: list[dict],
) -> list[SymbolDescriptor]:
    """
    Classify a list of raw symbol dicts from the ADS scanner.

    Each dict must have: full_name, type_name
    Optional keys:        comment, index_group, index_offset
    """
    result = []
    for raw in raw_symbols:
        sym = classify(
            full_name=raw.get("full_name", ""),
            type_name=raw.get("type_name", "UNKNOWN"),
            comment=raw.get("comment", ""),
        )
        sym.index_group  = raw.get("index_group",  0)
        sym.index_offset = raw.get("index_offset", 0)
        result.append(sym)
    return result
