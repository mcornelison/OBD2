################################################################################
# File Name: test_lifecycle.py
# Purpose/Description: Regression tests for lifecycle.py hardware-module import
#                      visibility (TD-015) and skip-path log level.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Ralph Agent  | US-207 TD-015: assert hardware-module import
#               |              | failures are logged (not silently swallowed)
#               |              | and that the "skipping HardwareManager" path
#               |              | logs at INFO, not DEBUG.
# 2026-04-23    | Ralph (Rex)  | US-222 / TD-030: update enabledFalseInConfig
#               |              | test to use the canonical pi.hardware.enabled
#               |              | path + add 4 regression tests pinning the
#               |              | canonical-path behavior (missing / true /
#               |              | false / top-level-ignored).
# ================================================================================
################################################################################

"""
TD-015 regression: hardware-module import visibility + skip-path log level.

On-Pi the import was failing silently through the main.py import chain while
succeeding via direct-module load. This class of bug is impossible to diagnose
when the exception is swallowed. These tests pin the visibility invariants:

1. When ``HARDWARE_AVAILABLE`` resolves True, both the direct-load path and
   a fresh import via ``importlib.reload`` agree. (Meta-invariant: the module
   flag is a clean boolean reflecting the try/except outcome.)
2. When the hardware import fails, the exception is logged at INFO level with
   type + message so operators can see it in ``journalctl`` without --verbose.
3. ``_initializeHardwareManager`` logs its skip reason at INFO, not DEBUG.
"""

from __future__ import annotations

import importlib
import logging
import sys
from unittest.mock import MagicMock

import pytest

# ================================================================================
# TD-015 invariant 1 — HARDWARE_AVAILABLE is a clean boolean matching import outcome
# ================================================================================


def test_hardwareAvailable_directImport_returnsBoolean():
    """
    Given: lifecycle.py loaded directly (pytest path)
    When:  HARDWARE_AVAILABLE attribute is read
    Then:  it is a bool (not None, not a module, not a half-initialized marker).
    """
    from pi.obdii.orchestrator import lifecycle

    assert isinstance(lifecycle.HARDWARE_AVAILABLE, bool)


# ================================================================================
# TD-015 invariant 2 — ImportError is logged, not swallowed
# ================================================================================


def test_hardwareImportError_emitsInfoLog_whenImportFails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: pi.hardware.hardware_manager import fails
    When:  lifecycle.py is reloaded
    Then:  an INFO-level log is emitted naming the exception type + message,
           so a Pi-side main.py chain failure would surface in journals.
    """
    # Arrange: block pi.hardware.* in sys.modules so re-import raises
    blocked = {}
    for modName in [
        "pi.hardware.hardware_manager",
        "pi.hardware.platform_utils",
        "pi.hardware",
    ]:
        blocked[modName] = sys.modules.pop(modName, None)

    # Poison the import so any attempt raises ImportError with a traceable
    # message
    class _ExplodingFinder:
        def find_spec(self, name, path, target=None):
            if name.startswith("pi.hardware"):
                raise ImportError(f"TD-015 synthetic block of {name}")
            return None

    finder = _ExplodingFinder()
    sys.meta_path.insert(0, finder)

    try:
        with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
            if "pi.obdii.orchestrator.lifecycle" in sys.modules:
                sys.modules.pop("pi.obdii.orchestrator.lifecycle")
            lifecycle = importlib.import_module("pi.obdii.orchestrator.lifecycle")

        assert lifecycle.HARDWARE_AVAILABLE is False

        importFailureLogs = [
            r
            for r in caplog.records
            if "Hardware module import skipped" in r.message
        ]
        assert importFailureLogs, (
            "TD-015: hardware-import ImportError must be logged (not swallowed) "
            "so Pi-side import-chain bugs surface in journal output."
        )
        assert any("ImportError" in r.message for r in importFailureLogs), (
            "Log should include exception type name for diagnostic clarity."
        )

    finally:
        # Cleanup: remove finder, restore any blocked modules, reload lifecycle
        sys.meta_path.remove(finder)
        for modName, mod in blocked.items():
            if mod is not None:
                sys.modules[modName] = mod
        sys.modules.pop("pi.obdii.orchestrator.lifecycle", None)
        importlib.import_module("pi.obdii.orchestrator.lifecycle")


# ================================================================================
# TD-015 invariant 3 — Skip-path log is INFO, not DEBUG
# ================================================================================


def test_initializeHardwareManager_hardwareUnavailable_logsAtInfoLevel(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE is False on a non-Pi system
    When:  _initializeHardwareManager is invoked
    Then:  the skip message is logged at INFO (not DEBUG), so operators see
           it in normal journal output without needing --verbose.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", False)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {}  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
        mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    infoLogs = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "Hardware module not available" in r.message
    ]
    assert infoLogs, (
        "TD-015: the 'Hardware module not available' skip message must be "
        "logged at INFO so it appears in normal journal output."
    )


def test_initializeHardwareManager_notPi_logsAtInfoLevel(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE is True but isRaspberryPi() returns False
    When:  _initializeHardwareManager is invoked
    Then:  the non-Pi skip message is logged at INFO (not DEBUG).
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: False)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {}  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
        mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    infoLogs = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "Not running on Raspberry Pi" in r.message
    ]
    assert infoLogs, (
        "TD-015: the 'Not running on Raspberry Pi' skip message must be "
        "logged at INFO so it appears in normal journal output."
    )


def test_initializeHardwareManager_enabledFalseInConfig_logsAtInfoLevel(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True, running on Pi, but pi.hardware.enabled=False
    When:  _initializeHardwareManager is invoked
    Then:  the config-disabled skip message logs at INFO.

    US-222 / TD-030 note: pre-US-222 this test pinned the top-level
    ``{"hardware": {"enabled": False}}`` path, which only worked because the
    code read the wrong key and never actually exercised a disable. The
    correct canonical path is ``pi.hardware.enabled`` (config.json nests
    hardware under the pi tier); this test now pins the real disable path.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: True)

    mixin = lifecycle.LifecycleMixin()
    # US-222: canonical path is pi.hardware.enabled, NOT top-level hardware.
    mixin._config = {"pi": {"hardware": {"enabled": False}}}  # type: ignore[attr-defined]
    mixin._hardwareManager = None  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
        mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    disabledLogs = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "HardwareManager disabled by configuration" in r.message
    ]
    assert disabledLogs, (
        "pi.hardware.enabled=False must log at INFO -- pinned to catch "
        "any accidental regression to DEBUG level."
    )


# ================================================================================
# US-222 / TD-030 — pi.hardware.enabled canonical config key path
# ================================================================================


def test_initializeHardwareManager_missingKey_defaultsToEnabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True, running on Pi, pi.hardware.enabled key absent
    When:  _initializeHardwareManager is invoked
    Then:  hardware init is reached (default True preserved); the
           "disabled by configuration" short-circuit is NOT taken.

    Pins backward-compat invariant from US-222: missing key must still
    default to enabled=True so operators who never set the key keep the
    pre-fix behavior.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: True)

    # Sentinel: if the default-True path is reached, this gets called.
    createSentinel = MagicMock(side_effect=RuntimeError("reached init"))
    monkeypatch.setattr(lifecycle, "createHardwareManagerFromConfig", createSentinel)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {}  # type: ignore[attr-defined]  # no pi.hardware.enabled key at all
    mixin._hardwareManager = None  # type: ignore[attr-defined]
    mixin._database = None  # type: ignore[attr-defined]

    mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    createSentinel.assert_called_once()


def test_initializeHardwareManager_piHardwareEnabledTrue_reachesHardwareInit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True, running on Pi, pi.hardware.enabled=True
    When:  _initializeHardwareManager is invoked
    Then:  hardware init is reached (the disable branch is NOT taken).

    Explicit opt-in mirror of the missing-key default path.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: True)

    createSentinel = MagicMock(side_effect=RuntimeError("reached init"))
    monkeypatch.setattr(lifecycle, "createHardwareManagerFromConfig", createSentinel)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {"pi": {"hardware": {"enabled": True}}}  # type: ignore[attr-defined]
    mixin._hardwareManager = None  # type: ignore[attr-defined]
    mixin._database = None  # type: ignore[attr-defined]

    mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    createSentinel.assert_called_once()


def test_initializeHardwareManager_piHardwareEnabledFalse_skipsHardwareInit(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True, running on Pi, pi.hardware.enabled=False
    When:  _initializeHardwareManager is invoked
    Then:  createHardwareManagerFromConfig is NEVER called (disable
           actually takes effect) AND the INFO log records the skip.

    US-222 / TD-030 core behavior change: pre-fix this path was silently
    ignored because the code read the wrong top-level key. Post-fix
    setting pi.hardware.enabled=False must short-circuit hardware init.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: True)

    createSentinel = MagicMock(side_effect=RuntimeError("should not be called"))
    monkeypatch.setattr(lifecycle, "createHardwareManagerFromConfig", createSentinel)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {"pi": {"hardware": {"enabled": False}}}  # type: ignore[attr-defined]
    mixin._hardwareManager = None  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
        mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    createSentinel.assert_not_called()
    disabledLogs = [
        r
        for r in caplog.records
        if "HardwareManager disabled by configuration" in r.message
    ]
    assert disabledLogs, "disable branch must emit the skip log"


def test_initializeHardwareManager_topLevelHardwareEnabledFalse_isIgnored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True, running on Pi, top-level
           ``{"hardware": {"enabled": False}}`` (the pre-US-222 incorrect
           shape, no pi. nesting)
    When:  _initializeHardwareManager is invoked
    Then:  the disable branch is NOT taken -- only the canonical
           ``pi.hardware.enabled`` path controls the subsystem.

    Regression guard: if someone reverts the key-path fix, the top-level
    accidental-match comes back. This test catches that explicitly.
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: True)

    createSentinel = MagicMock(side_effect=RuntimeError("reached init"))
    monkeypatch.setattr(lifecycle, "createHardwareManagerFromConfig", createSentinel)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {"hardware": {"enabled": False}}  # type: ignore[attr-defined]  # incorrect shape, should be ignored
    mixin._hardwareManager = None  # type: ignore[attr-defined]
    mixin._database = None  # type: ignore[attr-defined]

    mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    createSentinel.assert_called_once()


def test_hardwareAvailableAllTrue_doesNotInvokeCreateHardwareManagerOnNonPi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given: HARDWARE_AVAILABLE True but isRaspberryPi() False
    When:  _initializeHardwareManager runs
    Then:  createHardwareManagerFromConfig is never called -- the Pi-only
           gate holds (regression guard against accidental ordering change
           that would let non-Pi code reach hardware init).
    """
    from pi.obdii.orchestrator import lifecycle

    monkeypatch.setattr(lifecycle, "HARDWARE_AVAILABLE", True)
    monkeypatch.setattr(lifecycle, "isRaspberryPi", lambda: False)

    sentinel = MagicMock(side_effect=RuntimeError("should not be called"))
    monkeypatch.setattr(lifecycle, "createHardwareManagerFromConfig", sentinel)

    mixin = lifecycle.LifecycleMixin()
    mixin._config = {}  # type: ignore[attr-defined]
    mixin._hardwareManager = None  # type: ignore[attr-defined]

    mixin._initializeHardwareManager()  # type: ignore[attr-defined]

    sentinel.assert_not_called()
