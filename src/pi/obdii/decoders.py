################################################################################
# File Name: decoders.py
# Purpose/Description: Spool Data v2 decoders for new Mode 01 PIDs + ELM_VOLTAGE
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-199 Spool Data v2 Story 1)
# ================================================================================
################################################################################

"""
Decoders for the 6 new PIDs + ELM_VOLTAGE adapter command (US-199).

Each decoder accepts a python-obd-shaped response object (``.value``,
optional ``.unit``, optional ``.is_null()``) and normalizes it into a
:class:`DecodedReading` carrying:

- ``valueNumeric`` — goes into ``realtime_data.value`` (REAL NOT NULL)
- ``unit``         — goes into ``realtime_data.unit`` (TEXT)
- ``textLabel``    — human-readable state for enum-style parameters;
                     when populated it replaces ``unit`` at DB-write time
                     so analysts can read ``FUEL_SYSTEM_STATUS='CL'``
                     without needing the enum-code legend.

Enum encoding for :func:`decodeFuelSystemStatus`
    0 = UNKNOWN
    1 = OL (open-loop cold / warmup)
    2 = CL (closed-loop)
    3 = OL-drive (open-loop under load or decel-fuel-cut)
    4 = OL-fault (open-loop, system failure)
    5 = CL-fault (closed-loop, sensor fault)

The registry :data:`PARAMETER_DECODERS` binds each Spool parameter_name
to the python-obd command name, the Mode 01 PID hex code (or ``None``
for adapter-level commands), the decoder callable, and the DB unit
field. The realtime logger consults this registry before falling back
to the legacy getattr(obdlib.commands, name) path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# DecodedReading
# ================================================================================


@dataclass(frozen=True)
class DecodedReading:
    """
    Normalized decoder output.

    Attributes:
        valueNumeric: Float for storage in realtime_data.value.
        unit: Short unit label (e.g., 'V', 'kPa', 's', 'count').
        textLabel: Optional enum / state label (e.g., 'CL', 'ON');
            when populated, overrides unit at DB-write time.
    """

    valueNumeric: float
    unit: str
    textLabel: str | None = None


# ================================================================================
# Fuel System Status (PID 0x03)
# ================================================================================


_FUEL_STATUS_ENUM: tuple[tuple[str, int, str], ...] = (
    # (match-substring-lowercase, code, label). Order matters — 'fault' must
    # match before the generic 'closed loop' / 'open loop' cases.
    ("fault with at least one oxygen sensor", 5, "CL-fault"),
    ("open loop due to system failure", 4, "OL-fault"),
    ("engine load", 3, "OL-drive"),
    ("deceleration", 3, "OL-drive"),
    ("closed loop", 2, "CL"),
    ("open loop", 1, "OL"),
)


def decodeFuelSystemStatus(response: Any) -> DecodedReading:
    """
    Decode Mode 01 PID 0x03 into Spool's OL/CL/OL-drive/OL-fault/CL-fault enum.

    python-obd returns a tuple ``(bank1_status_text, bank2_status_text)``;
    this decoder takes bank 1 (the Eclipse is single-bank). Unknown
    strings encode as 0 / "UNKNOWN" per the stopCondition #3 invariant
    (don't crash on surprises — surface via log).
    """
    raw = _extractRaw(response)
    text = _firstString(raw).lower()
    if not text:
        return DecodedReading(0.0, "fuel_status", "UNKNOWN")

    for match, code, label in _FUEL_STATUS_ENUM:
        if match in text:
            return DecodedReading(float(code), "fuel_status", label)

    logger.warning("decodeFuelSystemStatus: unknown status text=%r", text)
    return DecodedReading(0.0, "fuel_status", "UNKNOWN")


# ================================================================================
# MIL + DTC Count (PID 0x01)
# ================================================================================


def decodeMilStatus(response: Any) -> DecodedReading:
    """Extract MIL on/off bit from Mode 01 PID 0x01 STATUS response."""
    status = _extractRaw(response)
    milOn = _readStatusField(status, "MIL", default=False)
    return DecodedReading(
        valueNumeric=1.0 if milOn else 0.0,
        unit="mil",
        textLabel="ON" if milOn else "OFF",
    )


def decodeDtcCount(response: Any) -> DecodedReading:
    """Extract DTC count (0-127) from Mode 01 PID 0x01 STATUS response."""
    status = _extractRaw(response)
    count = _readStatusField(status, "DTC_count", default=0)
    try:
        countFloat = float(count)
    except (TypeError, ValueError):
        countFloat = 0.0
    return DecodedReading(valueNumeric=countFloat, unit="count")


# ================================================================================
# Runtime (PID 0x1F)
# ================================================================================


def decodeRuntimeSec(response: Any) -> DecodedReading:
    """Decode Mode 01 PID 0x1F to uint16 seconds since engine start."""
    value = _numericMagnitude(_extractRaw(response))
    return DecodedReading(valueNumeric=value, unit="s")


# ================================================================================
# Barometric Pressure (PID 0x33)
# ================================================================================


def decodeBarometricKpa(response: Any) -> DecodedReading:
    """Decode Mode 01 PID 0x33 to kPa (uint8 0-255)."""
    value = _numericMagnitude(_extractRaw(response))
    return DecodedReading(valueNumeric=value, unit="kPa")


# ================================================================================
# ELM_VOLTAGE (adapter-level ATRV)
# ================================================================================


def decodeBatteryVoltage(response: Any) -> DecodedReading:
    """Decode the ELM327 ATRV / python-obd ELM_VOLTAGE response.

    This is NOT a Mode 01 PID — the ELM327 measures pin 16 directly and
    returns it as a pint Quantity in volts. Session 23 confirmed PID
    0x42 unsupported, so this is the only path for battery voltage on
    the 2G Eclipse.
    """
    value = _numericMagnitude(_extractRaw(response))
    return DecodedReading(valueNumeric=value, unit="V")


# ================================================================================
# Post-cat O2 (PID 0x15)
# ================================================================================


def decodeO2PostCatVoltage(response: Any) -> DecodedReading:
    """Decode Mode 01 PID 0x15 post-cat O2 response.

    python-obd returns a ``(voltage, STFT)`` tuple. Per stopCondition
    #4 we store only the voltage field this story; STFT post-cat is a
    future-sprint call for Spool.
    """
    raw = _extractRaw(response)
    if isinstance(raw, (tuple, list)) and raw:
        value = _numericMagnitude(raw[0])
    else:
        value = _numericMagnitude(raw)
    return DecodedReading(valueNumeric=value, unit="V")


# ================================================================================
# Registry
# ================================================================================


@dataclass(frozen=True)
class ParameterDecoderEntry:
    """Binds a Spool parameter_name to its python-obd command + decoder."""

    parameterName: str
    obdCommand: str
    pidCode: str | None
    decoder: Callable[[Any], DecodedReading]
    description: str


PARAMETER_DECODERS: dict[str, ParameterDecoderEntry] = {
    "FUEL_SYSTEM_STATUS": ParameterDecoderEntry(
        parameterName="FUEL_SYSTEM_STATUS",
        obdCommand="FUEL_STATUS",
        pidCode="0x03",
        decoder=decodeFuelSystemStatus,
        description="Fuel system status enum (OL/CL/OL-drive/OL-fault/CL-fault)",
    ),
    "MIL_ON": ParameterDecoderEntry(
        parameterName="MIL_ON",
        obdCommand="STATUS",
        pidCode="0x01",
        decoder=decodeMilStatus,
        description="Malfunction Indicator Lamp (CEL) on/off",
    ),
    "DTC_COUNT": ParameterDecoderEntry(
        parameterName="DTC_COUNT",
        obdCommand="STATUS",
        pidCode="0x01",
        decoder=decodeDtcCount,
        description="Count of stored DTCs (0-127)",
    ),
    "RUNTIME_SEC": ParameterDecoderEntry(
        parameterName="RUNTIME_SEC",
        obdCommand="RUN_TIME",
        pidCode="0x1F",
        decoder=decodeRuntimeSec,
        description="Runtime since engine start (seconds)",
    ),
    "BAROMETRIC_KPA": ParameterDecoderEntry(
        parameterName="BAROMETRIC_KPA",
        obdCommand="BAROMETRIC_PRESSURE",
        pidCode="0x33",
        decoder=decodeBarometricKpa,
        description="Barometric pressure (kPa)",
    ),
    "BATTERY_V": ParameterDecoderEntry(
        parameterName="BATTERY_V",
        obdCommand="ELM_VOLTAGE",
        pidCode=None,  # adapter-level, not a Mode 01 PID
        decoder=decodeBatteryVoltage,
        description="Battery voltage via ELM327 ATRV (2G workaround — PID 0x42 unsupported)",
    ),
    "O2_BANK1_SENSOR2_V": ParameterDecoderEntry(
        parameterName="O2_BANK1_SENSOR2_V",
        obdCommand="O2_B1S2",
        pidCode="0x15",
        decoder=decodeO2PostCatVoltage,
        description="Post-catalyst O2 sensor voltage (conditional — probe-gated on 2G)",
    ),
}


# ================================================================================
# Internal helpers
# ================================================================================


def _extractRaw(response: Any) -> Any:
    """Pull the underlying value out of a python-obd response shell."""
    if response is None:
        return None
    if hasattr(response, "is_null"):
        try:
            if response.is_null():
                return None
        except Exception:  # noqa: BLE001
            pass
    return getattr(response, "value", response)


def _firstString(raw: Any) -> str:
    """Coerce raw response into the first status-string (tuple-first-element or bare string)."""
    if raw is None:
        return ""
    if isinstance(raw, (tuple, list)):
        return str(raw[0]) if raw else ""
    return str(raw)


def _numericMagnitude(raw: Any) -> float:
    """Pull a float out of a pint Quantity, SimpleNamespace-wrapped magnitude, or bare number."""
    if raw is None:
        return 0.0
    if hasattr(raw, "magnitude"):
        try:
            return float(raw.magnitude)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _readStatusField(status: Any, fieldName: str, default: Any) -> Any:
    """Read a field from an OBDStatus object OR a dict."""
    if status is None:
        return default
    if isinstance(status, dict):
        return status.get(fieldName, default)
    return getattr(status, fieldName, default)
