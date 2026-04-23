################################################################################
# File Name: test_error_classification.py
# Purpose/Description: Unit tests for the US-211 capture-boundary classifier.
#                      Pins the 3-bucket taxonomy (ADAPTER_UNREACHABLE /
#                      ECU_SILENT / FATAL) against canned exception
#                      signatures drawn from python-obd + rfcomm behavior.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.error_classification`.

Coverage: each of the three buckets exercised with multiple canned
exception instances representative of what surfaces from python-obd
and the bluetooth_helper layer. Boundary cases (TimeoutError with vs.
without rfcomm message, bare Exception with rfcomm substring) guard
against classification drift.
"""

from __future__ import annotations

import pytest

from src.pi.obdii.bluetooth_helper import BluetoothHelperError
from src.pi.obdii.error_classification import (
    CaptureErrorClass,
    classifyCaptureError,
)
from src.pi.obdii.obd_connection import (
    ObdConnectionError,
    ObdConnectionFailedError,
    ObdConnectionTimeoutError,
)

# ================================================================================
# ADAPTER_UNREACHABLE
# ================================================================================

@pytest.mark.parametrize(
    "exc",
    [
        OSError("No such device"),
        FileNotFoundError("/dev/rfcomm0 missing"),
        PermissionError("cannot access /dev/rfcomm0"),
        BluetoothHelperError("rfcomm bind 0 failed: Host is down"),
        ObdConnectionError("rfcomm bind failed: transport endpoint"),
        ObdConnectionFailedError("rfcomm release error"),
        Exception("rfcomm timeout after 5s"),
        Exception("BlueZ D-Bus returned NoSuchAdapter"),
    ],
    ids=[
        "bare_OSError",
        "FileNotFoundError_rfcomm",
        "PermissionError_rfcomm",
        "BluetoothHelperError",
        "ObdConnectionError_rfcomm",
        "ObdConnectionFailedError_rfcomm",
        "generic_exception_rfcomm_substring",
        "bluez_stderr_substring",
    ],
)
def test_classifyCaptureError_adapterUnreachable(exc):
    """All adapter-layer signatures bucket into ADAPTER_UNREACHABLE."""
    assert classifyCaptureError(exc) is CaptureErrorClass.ADAPTER_UNREACHABLE


# ================================================================================
# ECU_SILENT
# ================================================================================

@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("ECU did not respond"),
        ObdConnectionTimeoutError("timeout waiting for response 010D"),
        ObdConnectionError("no data returned"),
    ],
    ids=[
        "plain_TimeoutError",
        "ObdConnectionTimeoutError_no_rfcomm",
        "ObdConnectionError_ambiguous_no_rfcomm",
    ],
)
def test_classifyCaptureError_ecuSilent(exc):
    """Timeouts without adapter signature bucket into ECU_SILENT."""
    assert classifyCaptureError(exc) is CaptureErrorClass.ECU_SILENT


def test_classifyCaptureError_timeoutWithRfcommSignature_isAdapter():
    """Guard: a TimeoutError *with* rfcomm in its message wins adapter bucket.

    This is the key boundary case -- the wrong ordering would false-
    classify a BT drop as ECU_SILENT and skip the reconnect loop.
    """
    exc = ObdConnectionTimeoutError("rfcomm read timed out")
    assert classifyCaptureError(exc) is CaptureErrorClass.ADAPTER_UNREACHABLE


# ================================================================================
# FATAL
# ================================================================================

@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("parser produced an unexpected response"),
        ValueError("cannot decode PID value"),
        KeyError("missing config section"),
        AttributeError("Something broke in a callback"),
        ZeroDivisionError("divide by zero in stats"),
    ],
    ids=[
        "RuntimeError",
        "ValueError",
        "KeyError",
        "AttributeError",
        "ZeroDivisionError",
    ],
)
def test_classifyCaptureError_fatal(exc):
    """Generic code bugs surface as FATAL so systemd restarts the process."""
    assert classifyCaptureError(exc) is CaptureErrorClass.FATAL


def test_classifyCaptureError_controlFlowIsFatal():
    """KeyboardInterrupt / SystemExit never swallowed -- always FATAL."""
    assert classifyCaptureError(KeyboardInterrupt()) is CaptureErrorClass.FATAL
    assert classifyCaptureError(SystemExit(0)) is CaptureErrorClass.FATAL
    assert classifyCaptureError(MemoryError()) is CaptureErrorClass.FATAL


# ================================================================================
# Enum discipline
# ================================================================================

def test_captureErrorClass_enumMembers_exactThree():
    """Spool locked three classes; guard adds aren't silent."""
    members = {m.name for m in CaptureErrorClass}
    assert members == {
        'ADAPTER_UNREACHABLE',
        'ECU_SILENT',
        'FATAL',
    }
