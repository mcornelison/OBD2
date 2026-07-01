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
# 2026-06-30    | Ralph (Rex)  | US-402: pygame sunset -- make the factory's
#               |              | StatusDisplay resolution pi-aware so the
#               |              | canonical config.json path
#               |              | (pi.hardware.statusDisplay.enabled) is honored
#               |              | when the orchestrator passes the FULL config
#               |              | (lifecycle.py). Top-level path kept as a
#               |              | back-compat fallback (US-198 escape hatch).
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


# ================================================================================
# US-402 pygame sunset -- pi-nested config path is honored
# ================================================================================


class TestPiNestedConfigResolution:
    """US-402: the orchestrator (lifecycle.py) passes the FULL config to the
    factory, where the StatusDisplay overlay lives under the canonical nested
    path ``pi.hardware.statusDisplay`` (config.json). The factory reads
    ``hardware.statusDisplay`` (no ``pi.`` prefix), so before US-402 the nested
    flag was silently ignored and the overlay always launched on the default.

    The pygame sunset retires the overlay via ``config.json`` -- so the factory
    MUST honor the nested path. The flat (top-level) path stays a back-compat
    fallback (the US-198 escape hatch), and the nested value takes precedence.
    """

    def test_fromConfig_piNestedStatusDisplayEnabledFalse_honored(self):
        """
        Given: a FULL config with pi.hardware.statusDisplay.enabled=False
               (the shape the orchestrator actually passes)
        When:  createHardwareManagerFromConfig runs
        Then:  manager._displayEnabled is False -- the pygame overlay is retired.
        """
        config = {
            "pi": {
                "hardware": {
                    "statusDisplay": {"enabled": False}
                }
            }
        }
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayEnabled is False

    def test_fromConfig_piNestedStatusDisplayEnabledFalse_initSkipsConstruction(self):
        """
        Given: a FULL config that retires the overlay via the nested path
        When:  _initializeStatusDisplay runs
        Then:  self._statusDisplay stays None -- no pygame surface is created,
               so it can never coexist with the HTML carousel (F-4).
        """
        config = {
            "pi": {
                "hardware": {
                    "statusDisplay": {"enabled": False}
                }
            }
        }
        manager = createHardwareManagerFromConfig(config)
        manager._initializeStatusDisplay()

        assert manager._statusDisplay is None

    def test_fromConfig_piNestedForceSoftwareRendererFalse_honored(self):
        """
        Given: a FULL config with pi.hardware.statusDisplay.forceSoftwareRenderer=False
        When:  createHardwareManagerFromConfig runs
        Then:  manager._displayForceSoftwareRenderer reflects the nested value.
        """
        config = {
            "pi": {
                "hardware": {
                    "statusDisplay": {"forceSoftwareRenderer": False}
                }
            }
        }
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayForceSoftwareRenderer is False

    def test_fromConfig_nestedDisablePrecedesFlatEnable(self):
        """
        Given: a config carrying BOTH the nested (pi.hardware.statusDisplay) and
               the flat (hardware.statusDisplay) paths with conflicting values
        When:  the factory resolves the flag
        Then:  the canonical nested path wins (False) -- the deployed config.json
               cut-over is authoritative over a stale flat override.
        """
        config = {
            "pi": {"hardware": {"statusDisplay": {"enabled": False}}},
            "hardware": {"statusDisplay": {"enabled": True}},
        }
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayEnabled is False

    def test_fromConfig_flatPathStillHonored_backCompat(self):
        """
        Given: the legacy flat-only config (no pi section) -- the US-198 shape
        When:  the factory resolves the flag
        Then:  the flat path still works (enabled=False honored), so the US-198
               operator escape hatch is preserved.
        """
        config = {"hardware": {"statusDisplay": {"enabled": False}}}
        manager = createHardwareManagerFromConfig(config)

        assert manager._displayEnabled is False
