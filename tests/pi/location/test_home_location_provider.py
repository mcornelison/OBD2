################################################################################
# File Name: test_home_location_provider.py
# Purpose/Description: Tests for the HomeLocationProvider SSOT (US-517 / F-125)
#                      -- the single read path for the pi.location.home fact.
#                      NOTE: every coordinate here is a FABRICATED test fixture.
#                      The CIO's real home coordinates live ONLY in the
#                      gitignored .env and must never appear in this tree.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial (US-517): honest-unknown coercion of the
#               |              | always-string .env surface + PII log discipline.
# ================================================================================
################################################################################
"""Unit tests for :mod:`pi.location.home_location_provider`."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from pi.location.home_location_provider import (
    HomeLocation,
    HomeLocationProvider,
)

# Fabricated fixture coordinates -- deliberately nowhere near the real home.
FAKE_LAT = 12.25
FAKE_LON = -34.75
FAKE_ELEV_M = 100.0


def buildConfig(
    lat: Any = FAKE_LAT,
    lon: Any = FAKE_LON,
    elevationM: Any = FAKE_ELEV_M,
) -> dict[str, Any]:
    """Build a tier-aware config carrying a pi.location.home section."""
    return {
        'pi': {
            'location': {
                'home': {'lat': lat, 'lon': lon, 'elevationM': elevationM},
            },
        },
    }


class TestHomeElevation:
    """pi.location.home.elevationM -- the US-518 altitude anchor."""

    def test_getHomeElevationM_realValue_returnsFloat(self):
        """
        Given: a config carrying a valid elevation
        When: getHomeElevationM is called
        Then: the elevation is returned as a float
        """
        provider = HomeLocationProvider.fromConfig(buildConfig())

        assert provider.getHomeElevationM() == pytest.approx(FAKE_ELEV_M)

    def test_getHomeElevationM_envStringValue_isCoercedToFloat(self):
        """
        Given: an elevation that came through secrets_loader (always a STRING)
        When: getHomeElevationM is called
        Then: it is coerced to a float, not returned as a string

        The whole .env surface arrives as strings -- an uncoerced value would
        make every downstream sum a string concatenation or a TypeError.
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM='100'))

        result = provider.getHomeElevationM()

        assert isinstance(result, float)
        assert result == pytest.approx(100.0)

    def test_getHomeElevationM_unresolvedPlaceholder_returnsNone(self):
        """
        Given: PI_HOME_ELEVATION_M was never set, so secrets_loader left the
               raw ${...} placeholder in the config
        When: getHomeElevationM is called
        Then: None -- the honest unknown, never a fabricated anchor
        """
        provider = HomeLocationProvider.fromConfig(
            buildConfig(elevationM='${PI_HOME_ELEVATION_M}')
        )

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_unresolvedPlaceholder_logsTheActualRemedy(self, caplog):
        """
        Given: an unresolved ${...} placeholder
        When: getHomeElevationM is called
        Then: the warning names the env var to set, not a generic parse error

        An unresolved placeholder and a typo'd number are different faults with
        different fixes; a shared "not a number" message hides which one it is.
        """
        provider = HomeLocationProvider.fromConfig(
            buildConfig(elevationM='${PI_HOME_ELEVATION_M}')
        )

        with caplog.at_level(logging.WARNING):
            provider.getHomeElevationM()

        assert 'PI_HOME_ELEVATION_M' in caplog.text

    def test_getHomeElevationM_emptyString_returnsNoneQuietly(self, caplog):
        """
        Given: an env var present but blank (the .env.example shipped state)
        When: getHomeElevationM is called
        Then: None, and NO warning -- "not configured" is not a fault
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=''))

        with caplog.at_level(logging.WARNING):
            assert provider.getHomeElevationM() is None

        assert caplog.text == ''

    def test_getHomeElevationM_nonNumeric_returnsNone(self):
        """
        Given: a typo'd, unparseable elevation
        When: getHomeElevationM is called
        Then: None rather than a crash or a guess
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM='20g'))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_nan_returnsNone(self):
        """
        Given: the literal string 'nan' (which float() accepts happily)
        When: getHomeElevationM is called
        Then: None -- a NaN anchor silently poisons every altitude derived
              from it, and NaN != NaN so nothing downstream detects it
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM='nan'))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_infinity_returnsNone(self):
        """
        Given: the literal string 'inf' (also accepted by float())
        When: getHomeElevationM is called
        Then: None
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM='inf'))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_boolean_returnsNone(self):
        """
        Given: a JSON `true` in the elevation slot
        When: getHomeElevationM is called
        Then: None -- float(True) is 1.0, a plausible-looking sea-level anchor
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=True))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_absurdlyHigh_returnsNone(self):
        """
        Given: an elevation above any point on Earth (a units/typo error)
        When: getHomeElevationM is called
        Then: None -- outside the physical band it cannot be a real anchor
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=12000))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_absurdlyLow_returnsNone(self):
        """
        Given: an elevation below the lowest dry land on Earth
        When: getHomeElevationM is called
        Then: None
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=-9999))

        assert provider.getHomeElevationM() is None

    def test_getHomeElevationM_belowSeaLevel_isAccepted(self):
        """
        Given: a legitimately negative elevation (below sea level is real)
        When: getHomeElevationM is called
        Then: the value is returned -- the guard rejects absurdity, not sign
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=-100.5))

        assert provider.getHomeElevationM() == pytest.approx(-100.5)


class TestHomeCoordinates:
    """pi.location.home.{lat,lon} -- the future GPS home-geofence."""

    def test_getHomeCoordinates_realValues_returnsLatLonTuple(self):
        """
        Given: a config carrying a valid lat and lon
        When: getHomeCoordinates is called
        Then: the (lat, lon) pair is returned as floats
        """
        provider = HomeLocationProvider.fromConfig(buildConfig())

        assert provider.getHomeCoordinates() == pytest.approx((FAKE_LAT, FAKE_LON))

    def test_getHomeCoordinates_envStringValues_areCoercedToFloats(self):
        """
        Given: lat/lon that arrived as strings from .env
        When: getHomeCoordinates is called
        Then: both are floats
        """
        provider = HomeLocationProvider.fromConfig(
            buildConfig(lat='12.25', lon='-34.75')
        )

        lat, lon = provider.getHomeCoordinates()

        assert isinstance(lat, float) and isinstance(lon, float)

    def test_getHomeCoordinates_latOutOfRange_returnsNone(self):
        """
        Given: a latitude outside [-90, 90]
        When: getHomeCoordinates is called
        Then: None -- not a place on Earth
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(lat=91.0))

        assert provider.getHomeCoordinates() is None

    def test_getHomeCoordinates_lonOutOfRange_returnsNone(self):
        """
        Given: a longitude outside [-180, 180]
        When: getHomeCoordinates is called
        Then: None
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(lon=-180.5))

        assert provider.getHomeCoordinates() is None

    def test_getHomeCoordinates_latPresentLonMissing_returnsNone(self):
        """
        Given: only half a coordinate pair
        When: getHomeCoordinates is called
        Then: None -- half a fix is not a location, it is a wrong one
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(lon=None))

        assert provider.getHomeCoordinates() is None

    def test_getHomeCoordinates_unresolvedPlaceholders_returnsNone(self):
        """
        Given: a Pi whose .env has no PI_HOME_LAT / PI_HOME_LON
        When: getHomeCoordinates is called
        Then: None
        """
        provider = HomeLocationProvider.fromConfig(
            buildConfig(lat='${PI_HOME_LAT}', lon='${PI_HOME_LON}')
        )

        assert provider.getHomeCoordinates() is None


class TestFactIndependence:
    """The elevation anchor and the coordinate pair are separate facts."""

    def test_getHomeElevationM_survivesMissingCoordinates(self):
        """
        Given: elevation configured but lat/lon absent
        When: getHomeElevationM is called
        Then: the elevation still resolves

        US-518 needs ONLY the elevation. Coupling it to a GPS fix the project
        does not yet have hardware for would strand the altitude re-anchor on
        a dependency it never needed.
        """
        provider = HomeLocationProvider.fromConfig(
            buildConfig(lat=None, lon=None)
        )

        assert provider.getHomeElevationM() == pytest.approx(FAKE_ELEV_M)
        assert provider.getHomeCoordinates() is None

    def test_getHomeCoordinates_survivesMissingElevation(self):
        """
        Given: lat/lon configured but elevation absent
        When: getHomeCoordinates is called
        Then: the pair still resolves
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=None))

        assert provider.getHomeCoordinates() == pytest.approx((FAKE_LAT, FAKE_LON))
        assert provider.getHomeElevationM() is None


class TestGetHome:
    """The composed all-three-facts view."""

    def test_getHome_allFieldsValid_returnsCompleteHomeLocation(self):
        """
        Given: a fully configured home reference
        When: getHome is called
        Then: a HomeLocation carrying all three values
        """
        provider = HomeLocationProvider.fromConfig(buildConfig())

        home = provider.getHome()

        assert home == HomeLocation(
            lat=FAKE_LAT, lon=FAKE_LON, elevationM=FAKE_ELEV_M
        )

    def test_getHome_anyFieldMissing_returnsNone(self):
        """
        Given: a partially configured home reference
        When: getHome is called
        Then: None -- the composed view is all-or-nothing
        """
        provider = HomeLocationProvider.fromConfig(buildConfig(elevationM=None))

        assert provider.getHome() is None


class TestMalformedConfig:
    """A malformed config surfaces as unknown, never as a crash."""

    @pytest.mark.parametrize(
        'config',
        [
            pytest.param({}, id='empty'),
            pytest.param({'pi': {}}, id='noLocationSection'),
            pytest.param({'pi': {'location': {}}}, id='noHomeSection'),
            pytest.param({'pi': {'location': {'home': None}}}, id='homeIsNone'),
            pytest.param({'pi': {'location': 'nope'}}, id='locationIsString'),
            pytest.param({'pi': None}, id='piIsNone'),
            pytest.param({'pi': 'nope'}, id='piIsString'),
        ],
    )
    def test_malformedConfig_resolvesToUnknownNotCrash(self, config):
        """
        Given: a config malformed anywhere along the pi.location.home path
        When: every accessor is called
        Then: the honest unknown, with no exception escaping
        """
        provider = HomeLocationProvider.fromConfig(config)

        assert provider.getHomeElevationM() is None
        assert provider.getHomeCoordinates() is None
        assert provider.getHome() is None


class TestPiiDiscipline:
    """Coordinates are PII and the log filter does not mask them."""

    def test_invalidCoordinate_isNotEchoedIntoTheLog(self, caplog):
        """
        Given: an out-of-range latitude that triggers a warning
        When: the warning is emitted
        Then: the coordinate VALUE never appears in the log text

        PIIMaskingFilter masks email/phone/SSN only (architecture.md sec 8) --
        a coordinate echoed into journald is PII leaked to a surface that has
        no mask for it. Name the KEY and the reason; never the value.
        """
        # 91.5 is out of range (so it warns) AND is fabricated -- a test that
        # needs a REAL coordinate to prove this would itself commit the PII.
        provider = HomeLocationProvider.fromConfig(buildConfig(lat=91.5))

        with caplog.at_level(logging.WARNING):
            provider.getHomeCoordinates()

        assert caplog.text, 'expected a warning to inspect'
        assert '91.5' not in caplog.text
        assert 'pi.location.home.lat' in caplog.text
