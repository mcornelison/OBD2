################################################################################
# File Name: test_altitude_anchor.py
# Purpose/Description: US-518 (WP-3, F-125) tests for AltitudeAnchor -- the
#   derived-altitude accumulator and its re-anchor to the home elevation on a
#   successful server sync.
#
#   The behaviour under test is drift control, so the tests are written around
#   the two ways it can lie: anchoring to a value it cannot vouch for, and
#   destroying a value it does not own. A sync-success with an UNKNOWN home
#   elevation must be a NO-OP -- not a reset to 0.0 (sea level in Chicagoland
#   is a 209 m error) and not a wipe of whatever the integrator had.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-518 sync-success altitude re-anchor.
# ================================================================================
################################################################################

"""US-518: derived-altitude accumulator + sync-success re-anchor tests."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from pi.location.altitude_anchor import AltitudeAnchor

# Fabricated elevation -- deliberately NOT the CIO's real 209 m home anchor.
# US-517's lesson: a test for a PII-adjacent rule must not use the real value
# as its fixture. Nothing here needs the true number to prove the behaviour.
FAKE_HOME_ELEVATION_M = 137.5


class _FakeHomeProvider:
    """Stands in for HomeLocationProvider: one fact, honestly unknown or not."""

    def __init__(self, elevationM: float | None = None, *, raises: bool = False):
        self.elevationM = elevationM
        self.raises = raises
        self.callCount = 0

    def getHomeElevationM(self) -> float | None:
        self.callCount += 1
        if self.raises:
            raise RuntimeError("config read exploded")
        return self.elevationM


def _anchorWithHome(elevationM: float | None = FAKE_HOME_ELEVATION_M) -> AltitudeAnchor:
    return AltitudeAnchor(_FakeHomeProvider(elevationM))


# ================================================================================
# 1. Initial state -- honest unknown, never a fabricated zero
# ================================================================================


class TestInitialState:
    def test_newAnchor_altitudeIsUnknown_notZero(self) -> None:
        """
        Given: a freshly constructed anchor
        When:  the altitude is read before any anchor or integration
        Then:  it is None -- 0.0 would render as sea level, a 209 m lie here
        """
        anchor = _anchorWithHome()

        assert anchor.getAltitudeM() is None

    def test_newAnchor_lastAnchoredAtIsNone(self) -> None:
        anchor = _anchorWithHome()

        assert anchor.getLastAnchoredAtIso() is None

    def test_construction_doesNotReadTheProvider(self) -> None:
        """The read is LAZY -- the boot-order trap that bit US-501/502/504b/505."""
        provider = _FakeHomeProvider(FAKE_HOME_ELEVATION_M)

        AltitudeAnchor(provider)

        assert provider.callCount == 0


# ================================================================================
# 2. The re-anchor itself (AC1)
# ================================================================================


class TestReanchorToHome:
    def test_knownElevation_setsAltitudeToIt(self) -> None:
        """
        Given: a known home elevation
        When:  the anchor re-anchors
        Then:  the accumulator holds exactly that elevation
        """
        anchor = _anchorWithHome(FAKE_HOME_ELEVATION_M)

        anchored = anchor.reanchorToHome()

        assert anchored is True
        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)

    def test_driftedAltitude_isResetToHome(self) -> None:
        """The story's whole point: bound the error to one drive between syncs."""
        anchor = _anchorWithHome(FAKE_HOME_ELEVATION_M)
        anchor.setDerivedAltitudeM(512.0)  # a drive's worth of integration drift

        anchor.reanchorToHome()

        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)

    def test_reanchor_stampsLastAnchoredAt(self) -> None:
        anchor = _anchorWithHome(FAKE_HOME_ELEVATION_M)

        anchor.reanchorToHome()

        stamp = anchor.getLastAnchoredAtIso()
        assert stamp is not None
        assert stamp.endswith("Z")

    def test_repeatedReanchor_isStable(self) -> None:
        anchor = _anchorWithHome(FAKE_HOME_ELEVATION_M)

        anchor.reanchorToHome()
        anchor.setDerivedAltitudeM(400.0)
        anchor.reanchorToHome()

        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)


# ================================================================================
# 3. Honest instrument -- unknown anchor is a NO-OP, never a guess or a wipe
# ================================================================================


class TestUnknownHomeElevation:
    def test_unknownElevation_doesNotAnchor(self) -> None:
        """
        Given: no home elevation configured (the Pi's real state today --
               deploy-pi.sh excludes .env, so PI_HOME_ELEVATION_M is unset)
        When:  a sync succeeds
        Then:  the anchor reports it did NOT anchor
        """
        anchor = _anchorWithHome(None)

        anchored = anchor.reanchorToHome()

        assert anchored is False

    def test_unknownElevation_leavesAltitudeUnknown(self) -> None:
        anchor = _anchorWithHome(None)

        anchor.reanchorToHome()

        assert anchor.getAltitudeM() is None

    def test_unknownElevation_doesNotDestroyAnExistingAltitude(self) -> None:
        """
        The anchor does not OWN the accumulator's value -- the US-519
        integrator does. Failing to improve an estimate is not licence to
        delete it, so an unanchorable sync must leave the value untouched.
        """
        anchor = _anchorWithHome(None)
        anchor.setDerivedAltitudeM(312.0)

        anchor.reanchorToHome()

        assert anchor.getAltitudeM() == pytest.approx(312.0)

    def test_unknownElevation_doesNotStampLastAnchoredAt(self) -> None:
        """"Last anchored" must mean it actually anchored, or it is a lie."""
        anchor = _anchorWithHome(None)

        anchor.reanchorToHome()

        assert anchor.getLastAnchoredAtIso() is None

    def test_unknownElevation_logsTheActualRemedy(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        US-517's lesson: an unresolved placeholder and a typo'd number have
        different fixes, so the log has to name the fix, not just the fault.
        """
        anchor = _anchorWithHome(None)

        with caplog.at_level(logging.DEBUG, logger="pi.location.altitude_anchor"):
            anchor.reanchorToHome()

        messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "PI_HOME_ELEVATION_M" in messages

    def test_providerRaises_isSwallowedAndReportsNotAnchored(self) -> None:
        """A config hiccup must never propagate into the sync path."""
        anchor = AltitudeAnchor(_FakeHomeProvider(raises=True))
        anchor.setDerivedAltitudeM(250.0)

        anchored = anchor.reanchorToHome()

        assert anchored is False
        assert anchor.getAltitudeM() == pytest.approx(250.0)

    def test_providerRaises_doesNotStampLastAnchoredAt(self) -> None:
        anchor = AltitudeAnchor(_FakeHomeProvider(raises=True))

        anchor.reanchorToHome()

        assert anchor.getLastAnchoredAtIso() is None


# ================================================================================
# 4. The sync-success hook (AC2 -- fires on success, and only on success)
# ================================================================================


class TestOnSyncSuccess:
    def test_onSyncSuccess_reanchors(self) -> None:
        anchor = _anchorWithHome(FAKE_HOME_ELEVATION_M)
        anchor.setDerivedAltitudeM(480.0)

        fired = anchor.onSyncSuccess()

        assert fired is True
        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)

    def test_onSyncSuccess_readsHomeEveryTime_notCachedAtConstruction(self) -> None:
        """
        The elevation can arrive AFTER the anchor is built (the CIO writes
        PI_HOME_ELEVATION_M into the Pi's .env, then the service is restarted
        -- or the config is re-read). A value cached at construction would make
        the anchor permanently dead on a box that later becomes configured.
        """
        provider = _FakeHomeProvider(None)
        anchor = AltitudeAnchor(provider)

        anchor.onSyncSuccess()
        assert anchor.getAltitudeM() is None

        provider.elevationM = FAKE_HOME_ELEVATION_M
        anchor.onSyncSuccess()

        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)


# ================================================================================
# 5. The integrator write seam (US-519 advances the accumulator through this)
# ================================================================================


class TestSetDerivedAltitude:
    def test_setsAFiniteValue(self) -> None:
        anchor = _anchorWithHome()

        accepted = anchor.setDerivedAltitudeM(275.25)

        assert accepted is True
        assert anchor.getAltitudeM() == pytest.approx(275.25)

    def test_acceptsBelowSeaLevel(self) -> None:
        """Negative elevations are real terrain, not an error."""
        anchor = _anchorWithHome()

        assert anchor.setDerivedAltitudeM(-42.0) is True
        assert anchor.getAltitudeM() == pytest.approx(-42.0)

    def test_setNone_returnsToHonestUnknown(self) -> None:
        """The integrator losing confidence is a legitimate state transition."""
        anchor = _anchorWithHome()
        anchor.setDerivedAltitudeM(300.0)

        assert anchor.setDerivedAltitudeM(None) is True
        assert anchor.getAltitudeM() is None

    @pytest.mark.parametrize(
        "bad",
        [
            float("nan"),
            float("inf"),
            float("-inf"),
        ],
        ids=["nan", "inf", "negInf"],
    )
    def test_rejectsNonFinite_leavingPriorValue(self, bad: float) -> None:
        """
        US-517's gotcha: NaN propagates silently through every later sum and
        never compares unequal to itself, so nothing downstream detects it.
        """
        anchor = _anchorWithHome()
        anchor.setDerivedAltitudeM(300.0)

        accepted = anchor.setDerivedAltitudeM(bad)

        assert accepted is False
        assert anchor.getAltitudeM() == pytest.approx(300.0)

    @pytest.mark.parametrize(
        "bad", [True, False], ids=["true", "false"]
    )
    def test_rejectsBool_leavingPriorValue(self, bad: Any) -> None:
        """float(True) == 1.0 -- a plausible-looking near-sea-level altitude."""
        anchor = _anchorWithHome()
        anchor.setDerivedAltitudeM(300.0)

        accepted = anchor.setDerivedAltitudeM(bad)

        assert accepted is False
        assert anchor.getAltitudeM() == pytest.approx(300.0)

    @pytest.mark.parametrize(
        "bad", ["300.0", "", [], {}], ids=["numericStr", "blank", "list", "dict"]
    )
    def test_rejectsNonNumeric_leavingPriorValue(self, bad: Any) -> None:
        anchor = _anchorWithHome()
        anchor.setDerivedAltitudeM(300.0)

        accepted = anchor.setDerivedAltitudeM(bad)

        assert accepted is False
        assert anchor.getAltitudeM() == pytest.approx(300.0)

    def test_acceptsInt(self) -> None:
        anchor = _anchorWithHome()

        assert anchor.setDerivedAltitudeM(209) is True
        assert anchor.getAltitudeM() == pytest.approx(209.0)


# ================================================================================
# 6. fromConfig -- the real HomeLocationProvider over a real config shape
# ================================================================================


class TestFromConfig:
    def test_configuredElevation_anchorsToIt(self) -> None:
        """End-to-end over the REAL provider, not the fake."""
        config = {
            "pi": {"location": {"home": {"elevationM": FAKE_HOME_ELEVATION_M}}}
        }
        anchor = AltitudeAnchor.fromConfig(config)

        assert anchor.onSyncSuccess() is True
        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)

    def test_unresolvedPlaceholder_staysUnknown(self) -> None:
        """
        The Pi's actual state: deploy-pi.sh excludes .env, so resolveSecrets
        leaves the placeholder VERBATIM and the config holds a truthy string.
        """
        config = {
            "pi": {"location": {"home": {"elevationM": "${PI_HOME_ELEVATION_M}"}}}
        }
        anchor = AltitudeAnchor.fromConfig(config)

        assert anchor.onSyncSuccess() is False
        assert anchor.getAltitudeM() is None

    def test_emptyConfig_staysUnknown(self) -> None:
        anchor = AltitudeAnchor.fromConfig({})

        assert anchor.onSyncSuccess() is False
        assert anchor.getAltitudeM() is None
