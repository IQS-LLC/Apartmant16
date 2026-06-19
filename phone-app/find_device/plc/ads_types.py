"""
ADS ↔ Python type resolution system.

Provides a complete mapping from TwinCAT type strings to pyads PLCTYPE_*
constants, plus helpers for array/struct introspection and value normalisation.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import pyads

logger = logging.getLogger(__name__)


# ── Primary type map ──────────────────────────────────────────────────────────
#
# Maps every standard TwinCAT IEC-61131-3 type string to the corresponding
# pyads PLCTYPE_* constant.  Keys are uppercase strings matching what
# TwinCAT returns from symbol/type information.

ADS_TYPE_MAP: dict[str, Any] = {
    # Boolean
    "BOOL":    pyads.PLCTYPE_BOOL,

    # Unsigned integers
    "BYTE":    pyads.PLCTYPE_BYTE,
    "USINT":   pyads.PLCTYPE_USINT,
    "UINT":    pyads.PLCTYPE_UINT,
    "UDINT":   pyads.PLCTYPE_UDINT,
    "ULINT":   pyads.PLCTYPE_ULINT,

    # Signed integers
    "SINT":    pyads.PLCTYPE_SINT,
    "INT":     pyads.PLCTYPE_INT,
    "DINT":    pyads.PLCTYPE_DINT,
    "LINT":    pyads.PLCTYPE_LINT,

    # Bit-pattern words (no signed interpretation; mapped to unsigned equivalents)
    "WORD":    pyads.PLCTYPE_UINT,    # 16-bit bit pattern  → UINT
    "DWORD":   pyads.PLCTYPE_UDINT,   # 32-bit bit pattern  → UDINT
    "LWORD":   pyads.PLCTYPE_ULINT,   # 64-bit bit pattern  → ULINT

    # Floating point
    "REAL":    pyads.PLCTYPE_REAL,
    "LREAL":   pyads.PLCTYPE_LREAL,

    # Strings
    "STRING":  pyads.PLCTYPE_STRING,
    "WSTRING": pyads.PLCTYPE_STRING,  # wide string; use PLCTYPE_STRING for pyads

    # Time / date types (represented as DWORD/UDINT on the wire)
    "TIME":    pyads.PLCTYPE_UDINT,   # milliseconds
    "TOD":     pyads.PLCTYPE_UDINT,   # time-of-day, milliseconds since midnight
    "DATE":    pyads.PLCTYPE_UDINT,   # seconds since 1970-01-01
    "DT":      pyads.PLCTYPE_UDINT,   # date-and-time, seconds since 1970-01-01
    "LTIME":   pyads.PLCTYPE_ULINT,   # nanoseconds (64-bit)
}

# Types for which is_writable_type() returns True
_WRITABLE_BASE_TYPES: frozenset[str] = frozenset({
    "BOOL",
    "BYTE", "USINT", "UINT", "UDINT", "ULINT",
    "SINT", "INT", "DINT", "LINT",
    "WORD", "DWORD", "LWORD",
    "REAL", "LREAL",
    "STRING", "WSTRING",
    "TIME", "TOD", "DATE", "DT", "LTIME",
})

# Regex for STRING(n) / WSTRING(n) patterns, e.g. STRING(80), STRING(255)
_STRING_N_RE = re.compile(r'^W?STRING\s*\(\s*(\d+)\s*\)$', re.IGNORECASE)

# Regex for ARRAY [...] OF <type> patterns
_ARRAY_RE = re.compile(
    r'^ARRAY\s*\[(.+?)\]\s*OF\s+(.+)$',
    re.IGNORECASE,
)

# Regex for a single dimension like "0..15" or "1..16"
_DIM_RE = re.compile(r'(-?\d+)\s*\.\.\s*(-?\d+)')


# ── Type resolution ───────────────────────────────────────────────────────────

def resolve_plc_type(type_name: str) -> Optional[Any]:
    """
    Resolve a TwinCAT type string to the correct pyads PLCTYPE_* constant.

    Handles:
    - All standard types via ADS_TYPE_MAP
    - STRING(n) / WSTRING(n) patterns  → PLCTYPE_STRING
    - Unknown / struct types           → None

    Args:
        type_name: TwinCAT type string, e.g. "INT", "STRING(80)", "BOOL".

    Returns:
        A pyads PLCTYPE_* constant, or None if the type cannot be resolved.
    """
    if not type_name:
        return None

    normalised = type_name.strip().upper()

    # Direct map lookup (handles all base types including WORD, DWORD, etc.)
    if normalised in ADS_TYPE_MAP:
        return ADS_TYPE_MAP[normalised]

    # STRING(n) / WSTRING(n)
    if _STRING_N_RE.match(type_name.strip()):
        return pyads.PLCTYPE_STRING

    logger.debug("resolve_plc_type: no mapping for type %r", type_name)
    return None


# ── Writability check ─────────────────────────────────────────────────────────

def is_writable_type(type_name: str) -> bool:
    """
    Return True if the type can be written directly via read_by_name /
    write_by_name.  Returns False for ARRAY and STRUCT types that require
    special handling.

    Args:
        type_name: TwinCAT type string.

    Returns:
        bool
    """
    if not type_name:
        return False

    normalised = type_name.strip().upper()

    # ARRAY [...] OF ... is never directly writable via the simple API
    if normalised.startswith("ARRAY"):
        return False

    # STRING(n) variants are writable
    if _STRING_N_RE.match(type_name.strip()):
        return True

    # All other known base types
    if normalised in _WRITABLE_BASE_TYPES:
        return True

    # Unknown / struct types (e.g. "ST_DaliChannel", "E_SomeEnum")
    return False


# ── Value normalisation ───────────────────────────────────────────────────────

def parse_ads_value(raw_value: Any, type_name: str) -> Any:
    """
    Normalise a raw pyads read result into a clean Python-native value.

    Conversions:
        BOOL              → bool
        Integer types     → int
        REAL / LREAL      → float
        STRING / WSTRING  → str  (decoded if bytes)
        TIME / TOD / DATE → int  (raw milliseconds / seconds)
        None input        → None

    Args:
        raw_value: The value returned by pyads.
        type_name: TwinCAT type string.

    Returns:
        Python-native value, or None if raw_value is None.
    """
    if raw_value is None:
        return None

    normalised = type_name.strip().upper()
    # Strip SIZE suffix for STRING(n)
    base_type = _STRING_N_RE.sub("STRING", normalised) if _STRING_N_RE.match(normalised) else normalised

    try:
        if base_type == "BOOL":
            return bool(raw_value)

        if base_type in ("REAL", "LREAL"):
            return float(raw_value)

        if base_type in ("STRING", "WSTRING"):
            if isinstance(raw_value, bytes):
                return raw_value.decode("utf-8", errors="replace").rstrip("\x00")
            return str(raw_value)

        if base_type in (
            "BYTE", "USINT", "UINT", "UDINT", "ULINT",
            "SINT", "INT", "DINT", "LINT",
            "WORD", "DWORD", "LWORD",
            "TIME", "TOD", "DATE", "DT", "LTIME",
        ):
            return int(raw_value)

    except (ValueError, TypeError) as exc:
        logger.warning(
            "parse_ads_value: could not convert %r (type %s): %s",
            raw_value, type_name, exc,
        )

    # Fallback: return as-is
    return raw_value


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class AdsTypeInfo:
    """
    Resolved type information for a single TwinCAT symbol or field.

    Attributes:
        type_name:   Raw TwinCAT type string (e.g. "ARRAY [1..16] OF INT").
        plc_type:    Resolved pyads PLCTYPE_* constant, or None for structs.
        byte_size:   Size in bytes as reported by TwinCAT (0 if unknown).
        is_array:    True if this is an ARRAY type.
        array_dims:  List of (lower, upper) bound tuples for each dimension.
        is_struct:   True if this is a STRUCT type.
        is_enum:     True if this is an ENUM type.
        base_type:   Base element type string for arrays / enums.
        enum_values: Mapping of enum member name → integer value.
    """
    type_name:   str
    plc_type:    Any                      = None
    byte_size:   int                      = 0
    is_array:    bool                     = False
    array_dims:  List[Tuple[int, int]]    = field(default_factory=list)
    is_struct:   bool                     = False
    is_enum:     bool                     = False
    base_type:   str                      = ""
    enum_values: dict[str, int]           = field(default_factory=dict)


# ── Array type parser ─────────────────────────────────────────────────────────

def parse_array_type(
    type_name: str,
) -> Optional[Tuple[str, List[Tuple[int, int]]]]:
    """
    Parse a TwinCAT ARRAY type string.

    Accepts formats like:
        ARRAY [1..16] OF INT
        ARRAY [0..7, 0..3] OF REAL
        ARRAY [1..10] OF ST_SomeStruct

    Args:
        type_name: Full TwinCAT type string.

    Returns:
        Tuple of (base_type_name, [(lower, upper), ...]) if this is an array
        type, or None if the string does not describe an array.
    """
    if not type_name:
        return None

    m = _ARRAY_RE.match(type_name.strip())
    if not m:
        return None

    dims_str   = m.group(1)   # e.g. "1..16" or "0..7, 0..3"
    base_type  = m.group(2).strip()

    dims: List[Tuple[int, int]] = []
    for dim_part in dims_str.split(","):
        dm = _DIM_RE.search(dim_part)
        if dm:
            dims.append((int(dm.group(1)), int(dm.group(2))))
        else:
            logger.warning(
                "parse_array_type: cannot parse dimension %r in %r",
                dim_part.strip(), type_name,
            )

    if not dims:
        return None

    return base_type, dims


# ── Struct field reader ───────────────────────────────────────────────────────

def parse_struct_type(plc: Any, type_name: str) -> List[Tuple[str, str]]:
    """
    Retrieve the field list for a TwinCAT STRUCT type.

    Attempts to call ``plc.get_datatype(type_name)`` which returns a
    ``AdsDatatype`` object (pyads >= 3.3).  Falls back gracefully on
    any exception (including mock mode where no real connection exists).

    Args:
        plc:       An ``ADSClient`` instance (or raw pyads.Connection).
                   If the object has a ``mock`` attribute set to True the
                   function returns an empty list immediately without making
                   any pyads call.
        type_name: TwinCAT struct name, e.g. "ST_DaliChannel".

    Returns:
        List of (field_name, field_type_string) tuples, or [] on failure.
    """
    # Honour mock mode: never call pyads in mock
    if getattr(plc, "mock", False):
        return []

    # Unwrap ADSClient → raw connection if needed
    conn = getattr(plc, "_conn", plc)
    if conn is None:
        return []

    try:
        dt = conn.get_datatype(type_name)
        if dt is None:
            return []

        fields: List[Tuple[str, str]] = []

        # pyads AdsDatatype exposes sub-items as a list of AdsSymbol-like objects
        sub_items = getattr(dt, "subItems", None) or getattr(dt, "sub_items", None) or []
        for item in sub_items:
            fname = getattr(item, "name", "") or getattr(item, "symbol_name", "")
            ftype = getattr(item, "type_name", "") or getattr(item, "dataTypeName", "")
            if fname:
                fields.append((str(fname), str(ftype)))

        return fields

    except Exception as exc:
        logger.debug(
            "parse_struct_type: could not read datatype %r: %s", type_name, exc
        )
        return []
