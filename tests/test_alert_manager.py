################################################################################
# File Name: test_alert_manager.py
# Purpose/Description: Tests for AlertManager class (direct unit tests)
# Author: Ralph Agent
# Creation Date: 2026-04-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-13    | Ralph Agent  | Sweep 2a task 3 — setThresholdsFromConfig TDD
# ================================================================================
################################################################################

"""
Unit tests for AlertManager class.

Tests the new setThresholdsFromConfig method added in Sweep 2a which builds
AlertThreshold objects from config['tieredThresholds'] and populates every
profile ID found in config['profiles']['availableProfiles'].

Usage:
    pytest tests/test_alert_manager.py -v
"""

import pytest

from alert.exceptions import AlertConfigurationError
from alert.manager import AlertManager
from alert.types import (
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_RPM_REDLINE,
    AlertDirection,
)

# ================================================================================
# Tests: AlertManager.setThresholdsFromConfig — Sweep 2a tiered rewire
# ================================================================================


class TestAlertManagerSetThresholdsFromConfig:
    """Tests for AlertManager.setThresholdsFromConfig — Sweep 2a tiered rewire."""

    def _minimalConfig(self, tieredOverrides=None, profiles=None):
        """Build a minimal config dict for testing. Override tieredThresholds or profiles as needed."""
        tiered = {
            'rpm': {'dangerMin': 7000, 'unit': 'rpm'},
            'coolantTemp': {'dangerMin': 220, 'unit': 'fahrenheit'},
        }
        if tieredOverrides is not None:
            tiered = tieredOverrides
        return {
            'tieredThresholds': tiered,
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': profiles or [
                    {'id': 'daily', 'name': 'Daily'},
                    {'id': 'performance', 'name': 'Performance'},
                ],
            },
        }

    def test_setThresholdsFromConfig_buildsRpmRedline_fromTieredDangerMin(self):
        """Given a tiered config with rpm.dangerMin=7000, builds an RPM ABOVE threshold at 7000."""
        # Arrange
        mgr = AlertManager()
        cfg = self._minimalConfig()

        # Act
        mgr.setThresholdsFromConfig(cfg)

        # Assert
        rpmThresholds = [t for t in mgr._profileThresholds['daily'] if t.parameterName == 'RPM']
        assert len(rpmThresholds) == 1
        assert rpmThresholds[0].threshold == 7000.0
        assert rpmThresholds[0].direction == AlertDirection.ABOVE
        assert rpmThresholds[0].alertType == ALERT_TYPE_RPM_REDLINE

    def test_setThresholdsFromConfig_buildsCoolantTempCritical_fromTieredDangerMin(self):
        """Given a tiered config with coolantTemp.dangerMin=220, builds a COOLANT_TEMP ABOVE threshold at 220."""
        # Arrange
        mgr = AlertManager()
        cfg = self._minimalConfig()

        # Act
        mgr.setThresholdsFromConfig(cfg)

        # Assert
        coolantThresholds = [t for t in mgr._profileThresholds['daily'] if t.parameterName == 'COOLANT_TEMP']
        assert len(coolantThresholds) == 1
        assert coolantThresholds[0].threshold == 220.0
        assert coolantThresholds[0].direction == AlertDirection.ABOVE
        assert coolantThresholds[0].alertType == ALERT_TYPE_COOLANT_TEMP_CRITICAL

    def test_setThresholdsFromConfig_populatesAllProfileIds(self):
        """Every profile in availableProfiles gets its own (identical) threshold list."""
        # Arrange
        mgr = AlertManager()
        cfg = self._minimalConfig(profiles=[
            {'id': 'daily', 'name': 'Daily'},
            {'id': 'performance', 'name': 'Performance'},
            {'id': 'track', 'name': 'Track'},
        ])

        # Act
        mgr.setThresholdsFromConfig(cfg)

        # Assert
        assert set(mgr._profileThresholds.keys()) >= {'daily', 'performance', 'track'}
        assert len(mgr._profileThresholds['daily']) == 2
        assert len(mgr._profileThresholds['performance']) == 2
        assert len(mgr._profileThresholds['track']) == 2
        # Each profile should have its own list object (so mutating one doesn't affect another)
        assert mgr._profileThresholds['daily'] is not mgr._profileThresholds['performance']

    def test_setThresholdsFromConfig_missingTieredSection_raisesError(self):
        """If config has no tieredThresholds key, raises AlertConfigurationError with a clear message."""
        # Arrange
        mgr = AlertManager()
        cfg = {'profiles': {'availableProfiles': [{'id': 'daily'}]}}

        # Act / Assert
        with pytest.raises(AlertConfigurationError) as exc_info:
            mgr.setThresholdsFromConfig(cfg)
        assert 'tieredThresholds' in str(exc_info.value)

    def test_setThresholdsFromConfig_skipsParametersNotInTiered(self):
        """Given a tiered config with only rpm, builds only the RPM threshold (no error on missing coolantTemp)."""
        # Arrange
        mgr = AlertManager()
        cfg = self._minimalConfig(tieredOverrides={'rpm': {'dangerMin': 7000, 'unit': 'rpm'}})

        # Act
        mgr.setThresholdsFromConfig(cfg)

        # Assert
        assert len(mgr._profileThresholds['daily']) == 1
        assert mgr._profileThresholds['daily'][0].parameterName == 'RPM'

    def test_setThresholdsFromConfig_rpmThresholdIs7000_matchesSpoolAuthoritative(self):
        """
        Integration check using the real src/obd_config.json — verifies RPM=7000 makes it all the way
        to AlertManager runtime state. This is the Spool-value preservation guarantee at the runtime layer.
        """
        # Arrange
        import json
        realConfig = json.load(open('Z:/o/OBD2v2/src/obd_config.json'))
        mgr = AlertManager()

        # Act
        mgr.setThresholdsFromConfig(realConfig)

        # Assert
        profileIds = list(mgr._profileThresholds.keys())
        assert len(profileIds) > 0
        firstProfile = mgr._profileThresholds[profileIds[0]]
        rpmThresholds = [t for t in firstProfile if t.parameterName == 'RPM']
        coolantThresholds = [t for t in firstProfile if t.parameterName == 'COOLANT_TEMP']
        assert len(rpmThresholds) == 1, f"Expected 1 RPM threshold, got {len(rpmThresholds)}"
        assert rpmThresholds[0].threshold == 7000.0, (
            f"Spool-authoritative RPM is 7000, got {rpmThresholds[0].threshold}"
        )
        assert rpmThresholds[0].direction == AlertDirection.ABOVE
        assert len(coolantThresholds) == 1
        assert coolantThresholds[0].threshold == 220.0
        assert coolantThresholds[0].direction == AlertDirection.ABOVE

    def test_setThresholdsFromConfig_boostAndOilNotSet_documented(self):
        """
        Document the intentional 2a gap: boost and oil pressure alerts are NOT wired.
        This test exists to ensure the gap is deliberate and visible. Delete when Spool
        adds boost/oil to tiered config and they get wired up in a follow-on sprint.
        """
        # Arrange
        mgr = AlertManager()
        cfg = self._minimalConfig()

        # Act
        mgr.setThresholdsFromConfig(cfg)

        # Assert
        builtThresholds = mgr._profileThresholds['daily']
        boostThresholds = [t for t in builtThresholds if t.parameterName in ('INTAKE_PRESSURE', 'BOOST_PRESSURE')]
        oilThresholds = [t for t in builtThresholds if t.parameterName == 'OIL_PRESSURE']
        assert len(boostThresholds) == 0, (
            "Boost alerts intentionally skipped in 2a — "
            "see offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md"
        )
        assert len(oilThresholds) == 0, (
            "Oil pressure alerts intentionally skipped in 2a — "
            "see offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md"
        )
