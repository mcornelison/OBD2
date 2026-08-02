################################################################################
# File Name: test_home_location_config_binding.py
# Purpose/Description: Tests the pi.location.home.{lat,lon,elevationM} config
#                      binding (US-517 / F-125) end-to-end against the REAL
#                      committed config.json: ${PI_HOME_*} placeholders resolve
#                      from the environment, the validator registers honest
#                      defaults, and NO location PII is ever committed.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial (US-517).
# ================================================================================
################################################################################
"""Config-binding tests for the home-location reference (US-517)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from common.config.secrets_loader import resolveSecrets
from common.config.validator import DEFAULTS, ConfigValidator

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / 'config.json'
ENV_EXAMPLE_PATH = REPO_ROOT / '.env.example'

HOME_KEYS = ('lat', 'lon', 'elevationM')
HOME_ENV_VARS = ('PI_HOME_LAT', 'PI_HOME_LON', 'PI_HOME_ELEVATION_M')

# Fabricated values -- never the real home reference.
FAKE_ENV = {
    'PI_HOME_LAT': '12.25',
    'PI_HOME_LON': '-34.75',
    'PI_HOME_ELEVATION_M': '100',
}


@pytest.fixture
def committedConfig() -> dict[str, Any]:
    """The real committed config.json, unresolved (placeholders intact)."""
    with open(CONFIG_PATH, encoding='utf-8') as handle:
        return json.load(handle)


class TestCommittedConfigCarriesNoPii:
    """The load-bearing guard: no coordinate may ever be committed."""

    def test_configJson_homeSection_holdsOnlyPlaceholders(self, committedConfig):
        """
        Given: the committed config.json
        When: the pi.location.home section is read
        Then: every value is a ${...} placeholder, never a literal value

        This is the PII invariant, not a style preference -- a coordinate
        committed here is in the repo's history permanently.
        """
        home = committedConfig['pi']['location']['home']

        for key in HOME_KEYS:
            assert re.fullmatch(r'\$\{[A-Z_]+\}', str(home[key])), (
                f'pi.location.home.{key} must be a bare ${{ENV_VAR}} placeholder, '
                f'got a committed literal'
            )

    def test_configJson_homeSection_bindsTheAgreedEnvVars(self, committedConfig):
        """
        Given: the committed config.json
        When: the placeholders are read
        Then: they name PI_HOME_LAT / PI_HOME_LON / PI_HOME_ELEVATION_M

        Iris already wrote these names into .env and .env.example; a rename
        here would silently unbind a correctly-populated .env.
        """
        home = committedConfig['pi']['location']['home']

        assert home['lat'] == '${PI_HOME_LAT}'
        assert home['lon'] == '${PI_HOME_LON}'
        assert home['elevationM'] == '${PI_HOME_ELEVATION_M}'

    def test_configJson_placeholdersCarryNoInlineDefault(self, committedConfig):
        """
        Given: the committed config.json
        When: the placeholders are read
        Then: none uses the ${VAR:default} form

        secrets_loader supports an inline default, and using it here would
        bake a fallback coordinate into source -- a fabricated location is
        worse than an absent one.
        """
        home = committedConfig['pi']['location']['home']

        for key in HOME_KEYS:
            assert ':' not in str(home[key]), (
                f'pi.location.home.{key} must not carry an inline default'
            )

    def test_validatorDefaults_registerNoCoordinateLiteral(self):
        """
        Given: the validator DEFAULTS registry
        When: the home-location entries are read
        Then: each default is None -- the registry mirrors config.json, so a
              real coordinate placed here would be committed PII too
        """
        for key in HOME_KEYS:
            path = f'pi.location.home.{key}'
            assert path in DEFAULTS, f'{path} missing from the DEFAULTS registry'
            assert DEFAULTS[path] is None, (
                f'{path} default must be None (honest unknown), not a value'
            )

    def test_envExample_documentsAllThreeVarsWithNoValues(self):
        """
        Given: the committed .env.example
        When: the PI_HOME_* lines are read
        Then: all three are documented and all three are blank
        """
        text = ENV_EXAMPLE_PATH.read_text(encoding='utf-8')

        for var in HOME_ENV_VARS:
            assert re.search(rf'^{var}=\s*$', text, re.MULTILINE), (
                f'{var} must be documented in .env.example with an EMPTY value'
            )


class TestPlaceholderResolution:
    """AC: the ${...} binding actually resolves from the environment."""

    def test_resolveSecrets_withEnvSet_resolvesAllThreeValues(
        self, committedConfig, monkeypatch
    ):
        """
        Given: PI_HOME_* set in the environment
        When: the real config.json is passed through resolveSecrets
        Then: pi.location.home carries the environment's values
        """
        for name, value in FAKE_ENV.items():
            monkeypatch.setenv(name, value)

        resolved = resolveSecrets(committedConfig)

        home = resolved['pi']['location']['home']
        assert home['lat'] == '12.25'
        assert home['lon'] == '-34.75'
        assert home['elevationM'] == '100'

    def test_resolveSecrets_withEnvUnset_leavesRawPlaceholder(
        self, committedConfig, monkeypatch
    ):
        """
        Given: no PI_HOME_* in the environment (a Pi whose .env lacks them --
               deploy-pi.sh excludes .env, so this is the REAL default state)
        When: the config is resolved
        Then: the raw ${...} string survives into the config

        Pinned deliberately: this string is truthy and non-None, so the
        validator's None-default never fires and the placeholder reaches the
        consumer. HomeLocationProvider is what must absorb it.
        """
        for name in HOME_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

        resolved = resolveSecrets(committedConfig)

        assert resolved['pi']['location']['home']['lat'] == '${PI_HOME_LAT}'


class TestValidatorBinding:
    """AC: validator default, and no new failure mode on the boot path."""

    def test_validate_absentSection_appliesHonestNoneDefaults(self, committedConfig):
        """
        Given: a config with no pi.location section at all
        When: it is validated
        Then: the keys exist with None -- shape guaranteed, value honest
        """
        committedConfig['pi'].pop('location', None)

        validated = ConfigValidator().validate(committedConfig)

        home = validated['pi']['location']['home']
        assert home == {'lat': None, 'lon': None, 'elevationM': None}

    def test_validate_realConfigJson_passes(self, committedConfig, monkeypatch):
        """
        Given: the real committed config.json with PI_HOME_* set
        When: it is loaded and validated the way the Pi loads it
        Then: validation succeeds and the values survive
        """
        for name, value in FAKE_ENV.items():
            monkeypatch.setenv(name, value)

        validated = ConfigValidator().validate(resolveSecrets(committedConfig))

        assert validated['pi']['location']['home']['elevationM'] == '100'

    @pytest.mark.parametrize(
        'badValue',
        [
            pytest.param('20g', id='typo'),
            pytest.param(91.0, id='latOutOfRange'),
            pytest.param('${PI_HOME_LAT}', id='unresolvedPlaceholder'),
            pytest.param('', id='blank'),
        ],
    )
    def test_validate_garbageHomeLocation_doesNotRaise(self, committedConfig, badValue):
        """
        Given: a malformed home-location value
        When: the config is validated
        Then: validation still succeeds

        Load-bearing: validate() runs on the Pi's boot path, and a raise here
        would refuse to start the orchestrator -- trading a dead OBD capture
        for a typo in an optional altitude anchor. The provider reports the
        honest unknown instead (same policy as pi.power.mode, US-421).
        """
        committedConfig['pi']['location']['home']['lat'] = badValue

        validated = ConfigValidator().validate(committedConfig)

        assert validated['pi']['location']['home']['lat'] == badValue
