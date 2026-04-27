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
# 2026-04-23    | Rex (US-229) | Added isEcuDependent metadata on every
#                               ParameterDecoderEntry + LEGACY_ECU_PARAMETERS
#                               frozenset + isEcuDependentParameter() helper
#                               so DriveDetector can distinguish ECU-sourced
#                               reads from the ELM_VOLTAGE adapter heartbeat.
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
    """Binds a Spool parameter_name to its python-obd command + decoder.

    Attributes:
        parameterName: Spool-facing name (stored in realtime_data).
        obdCommand: python-obd command name (``getattr(obd.commands, name)``).
        pidCode: Mode 01 PID hex string, or ``None`` for adapter-level commands.
        decoder: Callable normalizing python-obd responses into DecodedReading.
        description: Human-readable purpose / provenance note.
        isEcuDependent: ``True`` when the reading comes from the ECU
            (Mode 01/02/03/07/09), ``False`` when it's adapter-level
            (ELM327 ``ATRV``/``ATRZ`` etc.).  Used by DriveDetector
            (US-229) to distinguish real ECU liveness from the ELM
            voltmeter heartbeat so drive_end fires when the ECU goes
            silent, not when ``BATTERY_V`` keeps ticking.
    """

    parameterName: str
    obdCommand: str
    pidCode: str | None
    decoder: Callable[[Any], DecodedReading]
    description: str
    isEcuDependent: bool


PARAMETER_DECODERS: dict[str, ParameterDecoderEntry] = {
    "FUEL_SYSTEM_STATUS": ParameterDecoderEntry(
        parameterName="FUEL_SYSTEM_STATUS",
        obdCommand="FUEL_STATUS",
        pidCode="0x03",
        decoder=decodeFuelSystemStatus,
        description="Fuel system status enum (OL/CL/OL-drive/OL-fault/CL-fault)",
        isEcuDependent=True,
    ),
    "MIL_ON": ParameterDecoderEntry(
        parameterName="MIL_ON",
        obdCommand="STATUS",
        pidCode="0x01",
        decoder=decodeMilStatus,
        description="Malfunction Indicator Lamp (CEL) on/off",
        isEcuDependent=True,
    ),
    "DTC_COUNT": ParameterDecoderEntry(
        parameterName="DTC_COUNT",
        obdCommand="STATUS",
        pidCode="0x01",
        decoder=decodeDtcCount,
        description="Count of stored DTCs (0-127)",
        isEcuDependent=True,
    ),
    "RUNTIME_SEC": ParameterDecoderEntry(
        parameterName="RUNTIME_SEC",
        obdCommand="RUN_TIME",
        pidCode="0x1F",
        decoder=decodeRuntimeSec,
        description="Runtime since engine start (seconds)",
        isEcuDependent=True,
    ),
    "BAROMETRIC_KPA": ParameterDecoderEntry(
        parameterName="BAROMETRIC_KPA",
        obdCommand="BAROMETRIC_PRESSURE",
        pidCode="0x33",
        decoder=decodeBarometricKpa,
        description="Barometric pressure (kPa)",
        isEcuDependent=True,
    ),
    "BATTERY_V": ParameterDecoderEntry(
        parameterName="BATTERY_V",
        obdCommand="ELM_VOLTAGE",
        pidCode=None,  # adapter-level, not a Mode 01 PID
        decoder=decodeBatteryVoltage,
        description="Battery voltage via ELM327 ATRV (2G workaround — PID 0x42 unsupported)",
        # US-229: ELM_VOLTAGE is adapter-level (ATRV command); the dongle
        # measures pin 16 directly regardless of ECU state, so this
        # reading is NOT a signal that the engine is running.
        isEcuDependent=False,
    ),
    "O2_BANK1_SENSOR2_V": ParameterDecoderEntry(
        parameterName="O2_BANK1_SENSOR2_V",
        obdCommand="O2_B1S2",
        pidCode="0x15",
        decoder=decodeO2PostCatVoltage,
        description="Post-catalyst O2 sensor voltage (conditional — probe-gated on 2G)",
        isEcuDependent=True,
    ),
}


# ================================================================================
# US-229: ECU-dependency lookup for parameters NOT in PARAMETER_DECODERS
# ================================================================================


# Legacy Mode 01 parameter names queried via the ``getattr(obdlib.commands,
# name)`` fallback path in :meth:`ObdDataLogger.queryParameter` -- these
# don't go through a dedicated Spool v2 decoder, so they don't live in
# PARAMETER_DECODERS, but they are all ECU-sourced by OBD-II spec
# (Mode 01 = "request current powertrain data" from the ECU).
#
# Mirrors the polled Mode 01 PIDs from ``config.json`` pollingTiers
# (tier 1-4) EXCEPT those already served by PARAMETER_DECODERS entries
# (FUEL_SYSTEM_STATUS, MIL_ON, DTC_COUNT, RUNTIME_SEC, BAROMETRIC_KPA,
# O2_BANK1_SENSOR2_V, BATTERY_V).  Adding a new Mode 01 PID to
# config.json without also adding it here silently breaks the
# DriveDetector silence-check in US-229 -- the regression test in
# ``tests/pi/obdii/test_decoder_metadata.py::TestLegacyEcuParametersFrozenset``
# guards against that drift.
LEGACY_ECU_PARAMETERS: frozenset[str] = frozenset({
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "ENGINE_LOAD",
    "THROTTLE_POS",
    "TIMING_ADVANCE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "INTAKE_TEMP",
    "O2_B1S1",
    # CONTROL_MODULE_VOLTAGE PID 0x42 is probed-but-unsupported on the
    # 2G Eclipse per Session 23; kept in config.json for probe-matrix
    # documentation, kept here because if a non-2G future vehicle
    # supports it the reading IS ECU-sourced.
    "CONTROL_MODULE_VOLTAGE",
    # INTAKE_PRESSURE PID 0x0B is MDP (EGR only) on the 2G Eclipse, NOT
    # true MAP, but still an ECU Mode 01 read.
    "INTAKE_PRESSURE",
})


def isEcuDependentParameter(parameterName: str) -> bool:
    """Return ``True`` when a Spool parameter_name comes from the ECU.

    Used by :class:`DriveDetector` (US-229) to distinguish real ECU
    liveness signals (Mode 01/03/07/09 polls) from the ELM327 adapter
    voltmeter (``BATTERY_V``) when deciding whether to reset the
    drive-end silence timer.

    Resolution order:
        1. :data:`PARAMETER_DECODERS` entry -> entry's isEcuDependent flag
           (explicit metadata: 6/7 entries True, BATTERY_V False).
        2. :data:`LEGACY_ECU_PARAMETERS` -> True (legacy Mode 01 PIDs
           polled via the python-obd-command-name fallback path).
        3. Unknown -> False (safe default: unknown parameters do not
           extend drive_end spuriously; matches the US-229 invariant
           "Missing metadata defaults to False").

    Args:
        parameterName: Spool-facing parameter name (case-sensitive).

    Returns:
        True if the reading originates from the ECU; False for
        adapter-level commands or unknown parameter names.
    """
    entry = PARAMETER_DECODERS.get(parameterName)
    if entry is not None:
        return entry.isEcuDependent
    return parameterName in LEGACY_ECU_PARAMETERS


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
