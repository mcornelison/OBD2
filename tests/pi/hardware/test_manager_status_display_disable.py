################################################################################
# File Name: test_manager_status_display_disable.py
# Purpose/Description: createHardwareManagerFromConfig status_display config flags
# Author: Ralph Agent
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | US-198: TD-024 fix -- wire statusDisplay.enabled
#               |              | and statusDisplay.forceSoftwareRenderer through
#               |              | the factory so operators can disable the overlay
#               |              | or flip the renderer knob without code changes.
# ================================================================================
################################################################################

"""
Tests for createHardwareManagerFromConfig statusDisplay config flags.

Verifies:
- pi.hardware.statusDisplay.enabled = False skips StatusDisplay init entirely.
- pi.hardware.statusDisplay.forceSoftwareRenderer is threaded through the
  factory to the HardwareManager to the StatusDisplay constructor.
- Defaults are safe: enabled=True + forceSoftwareRenderer=True.

These flags are the US-198 operator-escape-hatch. In production the safer
default is enabled=True + software renderer; if the overlay ever breaks again
operators can set enabled=False to proceed without a rebuild.
"""

from pi.hardware.hardware_manager import (
    HardwareManager,
    createHardwareManagerFromConfig,
)

# ================================================================================
# Defaults
# ================================================================================


class TestFactoryDefaults:
    """Defaults favor safety: display enabled, software renderer forced."""

    def test_fromConfig_noStatusDisplaySection_defaultsToEnabledTrue(self):
        """
        Given: config with no pi.hardware.statusDisplay section
        When:  createHardwareManagerFromConfig runs
        Then:  _displayEnabled defaults to True (backwards compatible).
        """
        manager = createHardwareManagerFromConfig({})
        assert manager._displayEnabled is True

    def test_fromConfig_noStatusDisplaySection_defaultsToForceSoftwareTrue(self):
        """
        Given: config with no pi.hardware.statusDisplay section
        When:  createHardwareManagerFromConfig runs
        Then:  _displayForceSoftwareRenderer defaults to True -- the X11 safe path.
        """
        manager = createHardwareManagerFromConfig({})
        assert manager._displayForceSoftwareRenderer is True


# ================================================================================
# Explicit disable
# ================================================================================


class TestExplicitDisable:
    """The enabled=False operator escape hatch (stopCondition (d) in US-198)."""

    def test_fromConfig_statusDisplayEnabledFalse_threaded(self):
        """
        Given: config with hardware.statusDisplay.enabled=False
        When:  factory runs
        Then:  manager._displayEnabled reflects the config flag.
               Subsequent start() on non-Pi short-circuits before
               _initializeStatusDisplay, so no StatusDisplay is constructed.
        """
        config = {
            "hardware": {
                "statusDisplay": {"enabled": False}
            }
        }
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayEnabled is False

    def test_fromConfig_statusDisplayEnabledFalse_initSkipsConstruction(self):
        """
        Given: HardwareManager(_displayEnabled=False)
        When:  _initializeStatusDisplay runs
        Then:  self._statusDisplay stays None -- no pygame init attempted.
               This is the safety valve: even if pygame is broken, setting
               enabled=False yields a clean main.py launch.
        """
        manager = HardwareManager(displayEnabled=False)
        manager._initializeStatusDisplay()

        assert manager._statusDisplay is None


# ================================================================================
# forceSoftwareRenderer threading through the factory
# ================================================================================


class TestForceSoftwareRendererThreading:
    """
    The forceSoftwareRenderer value must cross 3 boundaries cleanly:
    config.json -> factory -> HardwareManager -> StatusDisplay.
    """

    def test_fromConfig_forceSoftwareRendererFalse_threaded(self):
        """
        Given: hardware.statusDisplay.forceSoftwareRenderer=False in config
        When:  factory runs
        Then:  manager._displayForceSoftwareRenderer is False.
        """
        config = {
            "hardware": {
                "statusDisplay": {"forceSoftwareRenderer": False}
            }
        }
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayForceSoftwareRenderer is False

    def test_hardwareManager_passesForceSoftwareRendererToStatusDisplay(self):
        """
        Given: HardwareManager constructed with displayForceSoftwareRenderer=False
        When:  _initializeStatusDisplay runs (with _isAvailable forced to True)
        Then:  the constructed StatusDisplay has forceSoftwareRenderer=False.
               This is the integration-level proof the flag survives wiring.
        """
        manager = HardwareManager(
            displayEnabled=True,
            displayForceSoftwareRenderer=False,
        )
        # StatusDisplay.__init__ runs isRaspberryPi internally -- that's fine on
        # non-Pi because we only care about the forceSoftwareRenderer attr.
        manager._initializeStatusDisplay()

        assert manager._statusDisplay is not None
        assert manager._statusDisplay.forceSoftwareRenderer is False

    def test_hardwareManager_defaultIsForceSoftwareRendererTrue(self):
        """
        Given: HardwareManager constructed with no explicit flag
        When:  _initializeStatusDisplay runs
        Then:  the StatusDisplay has forceSoftwareRenderer=True (safe default).
        """
        manager = HardwareManager(displayEnabled=True)
        manager._initializeStatusDisplay()

        assert manager._statusDisplay is not None
        assert manager._statusDisplay.forceSoftwareRenderer is True
