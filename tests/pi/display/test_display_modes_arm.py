################################################################################
# File Name: test_display_modes_arm.py
# Purpose/Description: ARM/Pi validation tests for the three DisplayManager
#                      driver modes (headless, minimal, developer) that are
#                      selectable via DISPLAY_MODE in config.json.  Confirms
#                      each mode initializes, shutdown is clean, and the
#                      minimal driver gracefully falls back to a null adapter
#                      when Adafruit SPI hardware is not present (which is the
#                      expected state on the OSOYOO-HDMI-only Pi 5).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation for US-178 (Pi Crawl)
# ================================================================================
################################################################################

"""
Display mode regression gate for Sprint 10 / US-178 (Pi Crawl).

These tests exercise the three display driver modes end-to-end against the
real DisplayManager on ARM (aarch64 Raspberry Pi OS) and on Windows.  They
do not depend on pygame, Adafruit SPI hardware, or the OSOYOO HDMI display
— the minimal driver is designed to fall back to a null adapter when no
Adafruit hardware is reachable, so the Pi under test (OSOYOO HDMI only)
still exercises minimal's code path without ever touching SPI.

Tests:
    test_displayMode_fromConfig_selectsCorrectDriver[mode]
        Confirms DisplayManager.fromConfig picks the right driver class for
        each DISPLAY_MODE value in config.json.

    test_displayMode_initializeShutdown_cleanLifecycle[mode]
        Exercises initialize -> showStatus -> showAlert -> shutdown against
        each driver without raising.  No hardware, no pygame — just the
        in-process driver tree.

    test_minimalDriver_noAdafruitHardware_fallsBackToNullAdapter
        Reproduces the OSOYOO-only Pi 5 state: Adafruit libs either missing
        or throwing on import.  Verifies the minimal driver logs the warning,
        installs the NullDisplayAdapter, and continues (does not raise).

    test_displayManager_invalidMode_defaultsToHeadless
        Protective path: an unknown DISPLAY_MODE string in config does not
        crash the orchestrator — it logs a warning and falls back to
        headless so the application stays up.
"""

from __future__ import annotations

import logging

import pytest

# tests/conftest.py puts src/ on sys.path.
from pi.display import (
    DeveloperDisplayDriver,
    DisplayMode,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    NullDisplayAdapter,
    createDisplayManagerFromConfig,
)

# ================================================================================
# Helpers
# ================================================================================


def _buildConfig(mode: str) -> dict[str, object]:
    """Build a minimal tier-aware config with the given display mode."""
    return {
        "pi": {
            "display": {
                "mode": mode,
                "width": 480,
                "height": 320,
                "refreshRateMs": 1000,
                "brightness": 100,
                "autoRefresh": False,   # keep tests deterministic
                "useHardware": False,   # don't try to open real Adafruit SPI
            }
        }
    }


# ================================================================================
# Mode-selection tests
# ================================================================================


@pytest.mark.parametrize(
    ("modeString", "expectedMode", "expectedDriverClass"),
    [
        ("headless", DisplayMode.HEADLESS, HeadlessDisplayDriver),
        ("minimal", DisplayMode.MINIMAL, MinimalDisplayDriver),
        ("developer", DisplayMode.DEVELOPER, DeveloperDisplayDriver),
    ],
)
def test_displayMode_fromConfig_selectsCorrectDriver(
    modeString: str,
    expectedMode: DisplayMode,
    expectedDriverClass: type,
) -> None:
    """
    Given: config.pi.display.mode = <headless|minimal|developer>
    When:  createDisplayManagerFromConfig(config) is called
    Then:  the resulting manager uses the matching DisplayMode enum value
           and instantiates the correct driver class.
    """
    config = _buildConfig(modeString)

    manager = createDisplayManagerFromConfig(config)

    assert manager.mode == expectedMode
    assert isinstance(manager._driver, expectedDriverClass)


def test_displayManager_invalidMode_defaultsToHeadless(caplog: pytest.LogCaptureFixture) -> None:
    """
    Given: config with an unknown display mode string
    When:  createDisplayManagerFromConfig(config) is called
    Then:  a warning is logged and the manager falls back to headless mode
           (application does not crash).
    """
    config = _buildConfig("not-a-real-mode")

    with caplog.at_level(logging.WARNING, logger="pi.display.manager"):
        manager = createDisplayManagerFromConfig(config)

    assert manager.mode == DisplayMode.HEADLESS
    assert isinstance(manager._driver, HeadlessDisplayDriver)
    assert any("Invalid display mode" in record.message for record in caplog.records)


# ================================================================================
# Lifecycle tests
# ================================================================================


@pytest.mark.parametrize(
    "modeString",
    ["headless", "minimal", "developer"],
)
def test_displayMode_initializeShutdown_cleanLifecycle(modeString: str) -> None:
    """
    Given: a DisplayManager for one of the 3 driver modes
    When:  initialize -> showStatus -> showAlert -> shutdown is exercised
    Then:  no exception is raised and isInitialized transitions
           False -> True -> False.
    """
    config = _buildConfig(modeString)
    manager = createDisplayManagerFromConfig(config)

    assert manager.isInitialized is False

    initialized = manager.initialize()
    try:
        # headless and developer always return True.  minimal returns True on
        # Pi even without Adafruit hardware (via NullDisplayAdapter).
        assert initialized is True
        assert manager.isInitialized is True

        # Exercise the status + alert code paths — these must not raise on
        # any driver.  Values are the kind of payload the orchestrator emits.
        manager.showStatus(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=2500.0,
            coolantTemp=85.0,
            activeAlerts=[],
            profileName="daily",
            powerSource="ac_power",
        )
        manager.showAlert(message="Test alert", priority=3)
    finally:
        manager.shutdown()

    assert manager.isInitialized is False


# ================================================================================
# Minimal driver graceful-degradation test (OSOYOO-only Pi 5)
# ================================================================================


def test_minimalDriver_noAdafruitHardware_fallsBackToNullAdapter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: minimal mode on a Pi 5 with OSOYOO HDMI only (no Adafruit 1.3" SPI)
    When:  the minimal driver initializes
    Then:  it detects no Adafruit hardware, logs a warning, installs a
           NullDisplayAdapter, and reports initialized=True so the
           orchestrator keeps running.

    This is the expected state on the Sprint 10 bench Pi (OSOYOO 3.5" HDMI
    attached, no Adafruit SPI attached).  Proving this fallback here means a
    future attempt to regress it (e.g. by making Adafruit unavailability a
    hard failure) will be caught by the fast suite.
    """
    config = _buildConfig("minimal")["pi"]["display"]  # type: ignore[index]
    assert isinstance(config, dict)

    driver = MinimalDisplayDriver(config=config)

    with caplog.at_level(logging.WARNING, logger="pi.display.drivers.minimal"):
        result = driver.initialize()

    try:
        assert result is True
        # NullDisplayAdapter is installed when Adafruit is unavailable
        assert isinstance(driver._displayAdapter, NullDisplayAdapter)
        assert any(
            "Adafruit display hardware not available" in record.message
            for record in caplog.records
        )
    finally:
        driver.shutdown()
