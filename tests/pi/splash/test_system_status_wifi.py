################################################################################
# File Name: test_system_status_wifi.py
# Purpose/Description: ARCH-007 -- the WiFi link fact in states/system-status,
#   built to the Atlas contract ruling of 2026-08-20 (Iris design gate).
# Author: Atlas (Architect)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-28    | Atlas   | ARCH-007: the glyph I ruled and then owed for 8 days
# ================================================================================
################################################################################

"""Acceptance tests for the `wifi` block in system-status.

Built to `reports/2026-08-20-wifi-glyph-contract-ruling.md`. The load-bearing
clauses, and why each is a test rather than a comment:

**§2.1 -- the emitter derives the band, the display does NOT.** `state` is
computed once here. If the glyph applied its own threshold there would be two
rules for one fact, and they would disagree the first time either moved.

**§2.3 -- unavailable resolves to `unknown`, never to a confident value.**
`down` is a MEASUREMENT: it means we looked and the link is not there. An
unreadable interface must yield `state: null` plus a typed reason, never `down`.
Rendering "no signal" when the truth is "we could not look" is the fabrication
class this project keeps finding.

**§2.2 -- thresholds are config, not code.** The weak/down boundary is a tuning
value; a magic number in the emitter is the defect Spool named five times.

Scope, from §4: the emitter field, the derivation, the availability block. NOT
the HomeNetworkDetector refactor, NOT history UI, and NOT any network management
-- **this fact is read-only. The Pi observes its link; it does not manage it.**
"""

import pytest

from src.pi.splash.system_status_emitter import buildSystemStatusState, deriveWifiState

_BASE = dict(
    obdLinkState="down", obdRetries=0, obdLastSeenS=None,
    syncLastOkTs=None, syncRows=0, syncPending=None, syncStale=False,
    powerSource="unknown",
    driveState="idle", driveId=None, nowIso="2026-08-28T00:00:00Z",
)


class TestTheEmitterDerivesTheBand:
    """Ruling §2.1 -- computed ONCE here, never in a consumer."""

    @pytest.mark.parametrize("rssi,expected", [
        (-45, "up"),      # strong
        (-60, "up"),      # comfortably above the boundary
        (-75, "weak"),    # between weak and down
        (-85, "weak"),    # still associated, poor
    ])
    def test_associatedRssiMapsToABand(self, rssi, expected):
        assert deriveWifiState(associated=True, rssiDbm=rssi,
                               weakRssiDbm=-70, downRssiDbm=-90) == expected

    def test_notAssociatedIsDownRegardlessOfAnyRssi(self):
        """Not associated is a measurement: we looked, there is no link."""
        assert deriveWifiState(associated=False, rssiDbm=None,
                               weakRssiDbm=-70, downRssiDbm=-90) == "down"

    def test_associatedButBelowTheDownFloorIsDown(self):
        assert deriveWifiState(associated=True, rssiDbm=-95,
                               weakRssiDbm=-70, downRssiDbm=-90) == "down"


class TestUnavailableIsNeverDown:
    """Ruling §2.3 -- the clause this whole contract exists to protect."""

    def test_anUnreadableInterfaceIsNullNotDown(self):
        assert deriveWifiState(associated=None, rssiDbm=None,
                               weakRssiDbm=-70, downRssiDbm=-90) is None

    def test_associatedButUnreadableRssiIsNullNotDown(self):
        """We know there is a link but cannot grade it -- that is not 'down'."""
        assert deriveWifiState(associated=True, rssiDbm=None,
                               weakRssiDbm=-70, downRssiDbm=-90) is None

    def test_theStateCarriesNullAndATypedReasonWhenUnavailable(self):
        s = buildSystemStatusState(
            **_BASE, wifiAvailable=False, wifiUnavailableReason="wifi: no interface")
        assert s["wifi"]["state"] is None
        assert s["source"]["wifi"]["available"] is False
        assert s["source"]["wifi"]["reason"] == "wifi: no interface"

    def test_anUnavailableLinkNeverReportsAnSsidOrRssi(self):
        """A stale SSID from the last association would be a fabricated fact."""
        s = buildSystemStatusState(
            **_BASE, wifiAvailable=False, wifiSsid="DeathstarWifi", wifiRssiDbm=-50)
        assert s["wifi"]["ssid"] is None
        assert s["wifi"]["rssiDbm"] is None


class TestTheBlockShapeMatchesTheRuling:
    """Ruling §2 -- the exact keys, alongside obdLink / sync / power / drive."""

    def test_theWifiBlockHasExactlyTheRuledKeys(self):
        s = buildSystemStatusState(**_BASE, wifiAvailable=True,
                                   wifiSsid="DeathstarWifi", wifiRssiDbm=-55)
        assert set(s["wifi"]) == {"state", "ssid", "rssiDbm"}
        assert s["wifi"] == {"state": "up", "ssid": "DeathstarWifi", "rssiDbm": -55}

    def test_wifiHasAnAvailabilityBlockLikeEveryOtherSource(self):
        s = buildSystemStatusState(**_BASE, wifiAvailable=True,
                                   wifiSsid="DeathstarWifi", wifiRssiDbm=-55)
        assert s["source"]["wifi"] == {"available": True, "reason": None}

    def test_theExistingSchemaIsUntouched(self):
        """Adding a source must not disturb the ones the cards already read."""
        s = buildSystemStatusState(**_BASE)
        for key in ("obdLink", "sync", "power", "drive", "idle", "ts"):
            assert key in s
        assert s["source"]["obd"]["available"] is True

    def test_wifiDefaultsToUnavailableNotToAFabricatedUp(self):
        """A caller that has not wired the provider must not publish a link."""
        s = buildSystemStatusState(**_BASE)
        assert s["wifi"]["state"] is None
        assert s["source"]["wifi"]["available"] is False


class TestThresholdsAreInjectedNotHardcoded:
    """Ruling §2.2 -- config, not magic numbers."""

    def test_movingTheBoundaryMovesTheVerdict(self):
        assert deriveWifiState(associated=True, rssiDbm=-65,
                               weakRssiDbm=-60, downRssiDbm=-90) == "weak"
        assert deriveWifiState(associated=True, rssiDbm=-65,
                               weakRssiDbm=-70, downRssiDbm=-90) == "up"
