################################################################################
# File Name: test_config_overlay.py
# Purpose/Description: Tests for the US-530 (F-126) Pi-local config OVERLAY and
#                      the SHARED resolveEffectiveConfig seam. config.json stays
#                      the read-only shipped default; a gitignored, deploy-
#                      excluded overlay layers OVER it so an operator toggle set
#                      on the Pi survives a deploy. The load-bearing assertion is
#                      the A-4 anti-divergence one: BOTH config readers (the
#                      orchestrator's loadConfigWithSecrets AND the state
#                      server's _loadDisplaySection) must resolve the SAME
#                      effective value through the SAME resolver.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Rex (US-530) | Initial -- overlay resolver, allow-list gate,
#               |              | both-reader parity, deploy-exclude durability.
# 2026-08-29    | Rex (US-572) | Comment-strip the --delete-excluded guard. It
#               |              | scanned RAW file text, so the US-553 comment
#               |              | that DOCUMENTS the ban in order to forbid it
#               |              | made the guard red on a correct script.
# 2026-10-23    | Rex (US-895-b)| MOVED PIN: the lux ends join the allow-list;
#               |              | their seam tests run through the real one.
# ================================================================================
################################################################################

"""Tests for the F-126 Pi-local config overlay (US-530).

Overlay contract under test:

* The overlay is a FLAT dot-path map (``{"pi.calibration.mode": true}``) stored
  beside config.json. Flat keys make the allow-list a literal key comparison at
  BOTH the read gate (here) and the US-531 write gate -- defense in depth.
* Effective value = allow-listed overlay override ELSE the config.json default.
* Honest-instrument: a malformed/absent overlay, an out-of-allow-list key, or a
  wrong-typed value resolves to the shipped default -- never a guessed value.
  (US-668 removed ``pi.power.mode``, which was the one coercion here.)
  (never a confident wrong mode).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from common.config import overlay as overlayModule
from common.config.overlay import (
    OVERRIDABLE_KEYS,
    applyConfigOverlay,
    crossKeyRefusal,
    enforceCrossKeyRules,
    loadOverlay,
    overlayPathFor,
    resolveEffectiveConfig,
    validateOverlayValue,
)
from common.config.secrets_loader import loadConfigWithSecrets
from common.config.validator import ConfigValidator
from pi.splash.states_http_server import loadDisplayCarouselConfig

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_PI_SH = REPO_ROOT / "deploy" / "deploy-pi.sh"
GITIGNORE = REPO_ROOT / ".gitignore"


def _writeConfig(tmp: Path, **overrides) -> Path:
    """Write a minimal tier-shaped config.json carrying every OVERRIDABLE_KEYS default.

    ``resumeIdleS`` is a NON-overridable neighbour inside the same
    ``display.carousel`` branch and is load-bearing: it is what
    ``test_bothReadPaths_agreeOnRejectingAnOutOfAllowListKey`` reads back at 45.
    Docstring said "the 5 Slice-1 keys" until US-603; the allow-list has been 3
    keys since US-533 dropped ``pi.alerts.audioAlerts`` and ``pi.power.mode``.
    MOVED PIN (US-895-b): 5 keys -- the autoDim lux ends, at the shipped 3 / 300.
    MOVED PIN (US-895-c): 6 keys -- overrideLevel null (auto), beside the
    shipped minLevel 0.75 that floors it.
    """
    config = {
        "protocolVersion": "1.0.0",
        "pi": {
            "display": {
                "carousel": {"autoRotateS": 8, "resumeIdleS": 45},
                "autoDim": {
                    "luxMin": 3.0,
                    "luxFull": 300.0,
                    "minLevel": 0.75,
                    "overrideLevel": None,
                },
            },
            "calibration": {"mode": False},
            "alerts": {"audioAlerts": False},
            "analysis": {"triggerAfterDrive": True},
        },
    }
    config.update(overrides)
    path = tmp / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _writeOverlay(configPath: Path, overlay: dict) -> Path:
    """Write an overlay beside the given config.json."""
    path = Path(overlayPathFor(str(configPath)))
    path.write_text(json.dumps(overlay), encoding="utf-8")
    return path


class TestResolveEffectiveConfig:
    """The shared resolver: overlay override ELSE config.json default."""

    def test_resolveEffectiveConfig_allowListedOverride_winsOverDefault(self):
        """
        Given: a base config with autoRotateS=8 and an overlay setting it to 0
        When: resolveEffectiveConfig() merges them
        Then: the effective value is the overlay's 0
        """
        base = {"pi": {"display": {"carousel": {"autoRotateS": 8, "resumeIdleS": 45}}}}

        effective = resolveEffectiveConfig(base, {"pi.display.carousel.autoRotateS": 0})

        assert effective["pi"]["display"]["carousel"]["autoRotateS"] == 0
        # Sibling keys under the same parent survive the merge.
        assert effective["pi"]["display"]["carousel"]["resumeIdleS"] == 45

    def test_resolveEffectiveConfig_emptyOverlay_returnsShippedDefault(self):
        """
        Given: a base config and NO overlay entries
        When: resolveEffectiveConfig() merges them
        Then: every value is the config.json default
        """
        base = {"pi": {"calibration": {"mode": False}, "alerts": {"audioAlerts": False}}}

        effective = resolveEffectiveConfig(base, {})

        assert effective["pi"]["calibration"]["mode"] is False
        assert effective["pi"]["alerts"]["audioAlerts"] is False

    def test_resolveEffectiveConfig_doesNotMutateBase(self):
        """
        Given: a base config that a caller may reuse
        When: resolveEffectiveConfig() applies an override
        Then: the base dict is untouched (deep copy, not in-place mutation)
        """
        base = {"pi": {"calibration": {"mode": False}}}

        effective = resolveEffectiveConfig(base, {"pi.calibration.mode": True})

        assert effective["pi"]["calibration"]["mode"] is True
        assert base["pi"]["calibration"]["mode"] is False

    def test_resolveEffectiveConfig_keyOutsideAllowList_ignoredAndLogged(
        self, caplog: pytest.LogCaptureFixture
    ):
        """
        Given: an overlay carrying a key that is NOT on the allow-list
        When: resolveEffectiveConfig() merges it
        Then: the key is not applied, and the rejection is logged
        """
        base = {"pi": {"obd": {"port": "/dev/rfcomm0"}}}

        with caplog.at_level(logging.WARNING):
            effective = resolveEffectiveConfig(base, {"pi.obd.port": "/dev/pwned"})

        assert effective["pi"]["obd"]["port"] == "/dev/rfcomm0"
        assert "pi.obd.port" in caplog.text

    def test_resolveEffectiveConfig_outOfAllowListKey_doesNotCreateNewBranch(self):
        """
        Given: an out-of-allow-list overlay key with no counterpart in the base
        When: resolveEffectiveConfig() merges it
        Then: no new config branch is invented (a rejected key writes nothing)
        """
        base = {"pi": {"calibration": {"mode": False}}}

        effective = resolveEffectiveConfig(base, {"pi.sync.serverUrl": "http://evil"})

        assert "sync" not in effective["pi"]

    @pytest.mark.parametrize("shipped,override", [(8, 0), (0, 8)])
    def test_resolveEffectiveConfig_autoRotateS_roundTripsZeroAndInterval(
        self, shipped: int, override: int
    ):
        """
        Given: autoRotateS as the ONE truth for auto-rotate (0=off, >0=on)
        When: the overlay flips it either direction
        Then: the effective value is the overlay's -- both directions round-trip
        """
        base = {"pi": {"display": {"carousel": {"autoRotateS": shipped}}}}

        effective = resolveEffectiveConfig(
            base, {"pi.display.carousel.autoRotateS": override}
        )

        assert effective["pi"]["display"]["carousel"]["autoRotateS"] == override

    # US-668 deleted test_resolveEffectiveConfig_validPowerMode_applied and
    # ..._invalidPowerMode_resolvesToUnknown. pi.power.mode was the only key with
    # a value VOCABULARY and the only COERCION in the overlay; both tests were
    # about that vocabulary. With the key gone there is no surviving key they
    # could be re-pointed at, so they are deleted rather than re-aimed at a code
    # path that no longer exists. The generic invalid-value path is still covered
    # by the key,bogus parametrisation directly below.

    @pytest.mark.parametrize(
        "key,bogus",
        [
            ("pi.display.carousel.autoRotateS", "8"),
            ("pi.display.carousel.autoRotateS", -1),
            ("pi.display.carousel.autoRotateS", True),
            ("pi.calibration.mode", 1),
            ("pi.analysis.triggerAfterDrive", "yes"),
        ],
    )
    def test_resolveEffectiveConfig_wrongTypedValue_fallsBackToDefault(self, key, bogus):
        """
        Given: an allow-listed key carrying a wrong-typed overlay value
        When: resolveEffectiveConfig() merges it
        Then: the shipped default stands -- a malformed overlay never guesses
        """
        base = {
            "pi": {
                "display": {"carousel": {"autoRotateS": 8}},
                "alerts": {"audioAlerts": False},
                "calibration": {"mode": False},
                "analysis": {"triggerAfterDrive": True},
            }
        }

        effective = resolveEffectiveConfig(base, {key: bogus})

        cursor = effective
        for part in key.split("."):
            cursor = cursor[part]
        expected = base
        for part in key.split("."):
            expected = expected[part]
        assert cursor == expected

    def test_resolveEffectiveConfig_explicitAllowlist_narrowsWhatApplies(self):
        """
        Given: an explicit allow-list narrower than the module default
        When: resolveEffectiveConfig() is called with it
        Then: only keys on the passed allow-list apply
        """
        base = {
            "pi": {
                "calibration": {"mode": False},
                "alerts": {"audioAlerts": False},
            }
        }

        effective = resolveEffectiveConfig(
            base,
            {"pi.calibration.mode": True, "pi.alerts.audioAlerts": True},
            allowlist=("pi.calibration.mode",),
        )

        assert effective["pi"]["calibration"]["mode"] is True
        assert effective["pi"]["alerts"]["audioAlerts"] is False


class TestSliceOneAllowList:
    """The Slice-1 overridable-key allow-list is itself the contract."""

    def test_overridableKeys_carriesExactlyTheFourSliceOneKeys(self):
        """
        Given: the Slice-1 allow-list (US-530, narrowed by US-533 B2)
        When: it is read
        Then: it is exactly the 4 agreed keys -- no silent widening

        pi.alerts.audioAlerts was DROPPED by CIO ruling 2026-08-07: it had no
        consumer anywhere in src/, so the control could only ever no-op. This
        assertion is a set, so it fails just as loudly on a re-add (which is
        US-538's job, alongside an actual audio path) as on a further drop.
        """
        # MOVED PIN (US-895-b): the autoDim lux ends join (CIO reversed Atlas
        # ruling B 2026-10-19), first in the table.
        # MOVED PIN (US-895-c): overrideLevel joins, first of all.
        assert set(OVERRIDABLE_KEYS) == {
            "pi.display.autoDim.overrideLevel",
            "pi.display.autoDim.luxMin",
            "pi.display.autoDim.luxFull",
            "pi.display.carousel.autoRotateS",
            "pi.calibration.mode",
            "pi.analysis.triggerAfterDrive",
        }

    def test_validateOverlayValue_sharedGate_rejectsOutOfAllowListKey(self):
        """
        Given: the write-side gate US-531 will reuse
        When: an out-of-allow-list key is validated
        Then: it is rejected -- one allow-list, both gates
        """
        ok, _ = validateOverlayValue("pi.obd.port", "/dev/pwned")

        assert ok is False

    def test_validateOverlayValue_validEntry_accepted(self):
        """
        Given: an allow-listed key with a well-typed value
        When: it is validated
        Then: it is accepted and the stored value is returned
        """
        ok, value = validateOverlayValue("pi.display.carousel.autoRotateS", 0)

        assert ok is True
        assert value == 0


_OVERRIDE_KEY = "pi.display.autoDim.overrideLevel"
_MIN_LEVEL_KEY = "pi.display.autoDim.minLevel"
_LUX_MIN_KEY = "pi.display.autoDim.luxMin"
_LUX_FULL_KEY = "pi.display.autoDim.luxFull"


def _autoDimBase(**autoDim) -> dict:
    """A base config whose pi.display.autoDim section is exactly ``autoDim``."""
    return {"pi": {"display": {"autoDim": dict(autoDim)}}}


# MOVED PIN (US-895-c): the autoDimOverridable fixture (and its _isLevelOrNone)
# patched overrideLevel into the allow-list for US-878-c; the key is in the REAL
# allow-list now, so every path below runs unpatched.


def _seamWarnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "invalid, using default" in r.getMessage()]


class TestCrossKeySeam:
    """US-878-c (Atlas A5/A6, B1-B3, B6): ONE function checks the cross-key rules
    on the EFFECTIVE config (overlay -> config.json -> validator DEFAULTS), so an
    overlay value can never stop ConfigValidator at boot."""

    def test_overrideBelowMinLevel_isDropped_andTheRuleIsNamed(self):
        """
        Given: effective minLevel 0.75 (config.json) and overrideLevel 0.5 (overlay)
        When: the seam checks the rules
        Then: overrideLevel is dropped under the rule 'overrideLevel >= minLevel'
        """
        kept, drops = enforceCrossKeyRules(_autoDimBase(minLevel=0.75), {_OVERRIDE_KEY: 0.5})

        assert kept == {}
        assert [(key, rule.name) for key, rule in drops] == [
            (_OVERRIDE_KEY, "overrideLevel >= minLevel")
        ]

    @pytest.mark.parametrize("level", [None, 0.75, 0.8, 1.0])
    def test_overrideNullOrAtOrAboveMinLevel_isKept(self, level):
        kept, drops = enforceCrossKeyRules(_autoDimBase(minLevel=0.75), {_OVERRIDE_KEY: level})

        assert kept == {_OVERRIDE_KEY: level}
        assert drops == []

    def test_minLevelMissingFromConfig_comparesAgainstTheValidatorDefault(self):
        """DEFAULTS minLevel is 0.15: 0.10 breaks it, 0.20 does not."""
        low, lowDrops = enforceCrossKeyRules(_autoDimBase(), {_OVERRIDE_KEY: 0.10})
        high, highDrops = enforceCrossKeyRules(_autoDimBase(), {_OVERRIDE_KEY: 0.20})

        assert (low, [k for k, _ in lowDrops]) == ({}, [_OVERRIDE_KEY])
        assert (high, highDrops) == ({_OVERRIDE_KEY: 0.20}, [])

    def test_bothLuxKeysInOverlayAndCrossed_bothDropped(self):
        kept, drops = enforceCrossKeyRules(
            _autoDimBase(luxMin=3.0, luxFull=300.0),
            {_LUX_MIN_KEY: 500.0, _LUX_FULL_KEY: 100.0},
        )

        assert kept == {}
        assert sorted(key for key, _ in drops) == [_LUX_FULL_KEY, _LUX_MIN_KEY]
        assert {rule.name for _, rule in drops} == {"luxFull > luxMin"}

    @pytest.mark.parametrize(
        ("overlayValues", "dropped"),
        [
            ({_LUX_FULL_KEY: 2.0}, _LUX_FULL_KEY),
            ({_LUX_MIN_KEY: 400.0}, _LUX_MIN_KEY),
        ],
    )
    def test_oneLuxKeyCrossed_onlyItIsDropped(self, overlayValues, dropped):
        """The config.json partner is not an overlay key, so it is never dropped."""
        others = {_OVERRIDE_KEY: 0.9, "pi.calibration.mode": True}
        kept, drops = enforceCrossKeyRules(
            _autoDimBase(luxMin=3.0, luxFull=300.0, minLevel=0.75),
            {**overlayValues, **others},
        )

        assert kept == others
        assert [key for key, _ in drops] == [dropped]

    def test_configLacksLuxMin_overlayLuxFullBelowTheDefault_isDropped(self):
        """luxMin falls back to DEFAULTS 3.0: luxFull 2.5 crosses it, 5.0 does not."""
        kept, drops = enforceCrossKeyRules(_autoDimBase(luxFull=300.0), {_LUX_FULL_KEY: 2.5})
        keptOk, dropsOk = enforceCrossKeyRules(_autoDimBase(luxFull=300.0), {_LUX_FULL_KEY: 5.0})

        assert (kept, [k for k, _ in drops]) == ({}, [_LUX_FULL_KEY])
        assert (keptOk, dropsOk) == ({_LUX_FULL_KEY: 5.0}, [])

    def test_aShippedConfigThatBreaksARule_isLeftToTheValidator(self):
        """No overlay key in the rule -> nothing to drop and no raise: a bad
        SHIPPED config still fails loud at ConfigValidator (US-627 AC-4)."""
        kept, drops = enforceCrossKeyRules(
            _autoDimBase(luxMin=500.0, luxFull=100.0), {"pi.calibration.mode": True}
        )

        assert kept == {"pi.calibration.mode": True}
        assert drops == []

    def test_doesNotMutateItsInputs(self):
        base = _autoDimBase(minLevel=0.75)
        overlayValues = {_OVERRIDE_KEY: 0.5}

        enforceCrossKeyRules(base, overlayValues)

        assert overlayValues == {_OVERRIDE_KEY: 0.5}
        assert base == _autoDimBase(minLevel=0.75)

    def test_stillBrokenAfterTheCap_raises(self, monkeypatch):
        """B2: the loop is capped at the rule count; a rule still broken after it
        is a code bug, so it raises instead of looping or guessing."""
        monkeypatch.setattr(overlayModule, "_ruleBrokenByOverlay", lambda *_: True)

        with pytest.raises(RuntimeError):
            enforceCrossKeyRules(_autoDimBase(minLevel=0.75), {_OVERRIDE_KEY: 0.5})

    def test_resolve_overrideBelowMinLevel_droppedWithOneWarningNamingTheRule(
        self, caplog
    ):
        """
        Given: overrideLevel 0.5 overridable and in the overlay, minLevel 0.75
        When: resolveEffectiveConfig runs
        Then: the config.json value stands, with ONE 'invalid, using default'
              warning that names the rule (B6)
        """
        base = _autoDimBase(minLevel=0.75, overrideLevel=None)

        with caplog.at_level(logging.WARNING):
            effective = resolveEffectiveConfig(base, {_OVERRIDE_KEY: 0.5})

        assert effective["pi"]["display"]["autoDim"]["overrideLevel"] is None
        warnings = _seamWarnings(caplog)
        assert len(warnings) == 1
        assert _OVERRIDE_KEY in warnings[0]
        assert "overrideLevel >= minLevel" in warnings[0]

    def test_resolve_bothLuxCrossed_bothDropped_eachLogged(self, caplog):
        # MOVED PIN (US-895-b): through the REAL allow-list, no patch.
        base = _autoDimBase(luxMin=3.0, luxFull=300.0)

        with caplog.at_level(logging.WARNING):
            effective = resolveEffectiveConfig(
                base, {_LUX_MIN_KEY: 500.0, _LUX_FULL_KEY: 100.0}
            )

        assert effective["pi"]["display"]["autoDim"] == {"luxMin": 3.0, "luxFull": 300.0}
        assert len(_seamWarnings(caplog)) == 2

    def test_resolve_aConsistentOverlayPair_isApplied(self):
        # MOVED PIN (US-895-b): through the REAL allow-list, no patch.
        base = _autoDimBase(luxMin=3.0, luxFull=300.0)

        effective = resolveEffectiveConfig(base, {_LUX_MIN_KEY: 10.0, _LUX_FULL_KEY: 500.0})

        assert effective["pi"]["display"]["autoDim"] == {"luxMin": 10.0, "luxFull": 500.0}

    def test_resolve_neverHandsTheValidatorACrossedPair(self, tmp_path):
        """The boot path: secrets_loader applies the overlay, then main.py
        validates. A crossing overlay must not fail ConfigValidator."""
        config = {"pi": {"display": {"autoDim": {"luxMin": 3.0, "luxFull": 300.0}}}}
        configPath = tmp_path / "config.json"
        configPath.write_text(json.dumps(config), encoding="utf-8")
        _writeOverlay(configPath, {_LUX_FULL_KEY: 1.0})

        effective = applyConfigOverlay(config, str(configPath))
        ConfigValidator(requiredKeys=[])._validateDisplayAutoDim(effective)

        assert effective["pi"]["display"]["autoDim"]["luxFull"] == 300.0

    def test_boot_handEditedCrossingLuxFull_oneWarningNamingTheRule_configValueStands(
        self, tmp_path, caplog
    ):
        """
        Given: config.json luxMin 3, config.local.json luxFull 2 (hand-edited)
        When: the orchestrator's read path loads and validates the config
        Then: it validates (eclipse-obd starts); exactly one WARNING names
              'luxFull > luxMin'; the effective luxFull is config.json's
              (US-895-b validationCriteria 3, real allow-list)
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {_LUX_FULL_KEY: 2})

        with caplog.at_level(logging.WARNING):
            config = loadConfigWithSecrets(str(configPath))
        ConfigValidator(requiredKeys=[])._validateDisplayAutoDim(config)

        assert config["pi"]["display"]["autoDim"]["luxFull"] == 300.0
        named = [m for m in _seamWarnings(caplog) if "luxFull > luxMin" in m]
        assert len(named) == 1
        assert _LUX_FULL_KEY in named[0]

    def test_crossKeyRefusal_namesTheRuleForACrossingWrite(self, tmp_path):
        configPath = tmp_path / "config.json"
        configPath.write_text(
            json.dumps(_autoDimBase(luxMin=3.0, luxFull=300.0)), encoding="utf-8"
        )

        refused = crossKeyRefusal(str(configPath), _LUX_FULL_KEY, 2.0)
        allowed = crossKeyRefusal(str(configPath), _LUX_FULL_KEY, 500.0)

        assert refused is not None
        assert refused.error == "luxFull must be greater than luxMin"
        assert allowed is None

    def test_crossKeyRefusal_unreadableConfig_judgesAgainstTheDefaults(self, tmp_path):
        configPath = tmp_path / "config.json"
        configPath.write_text("{not json", encoding="utf-8")

        assert crossKeyRefusal(str(configPath), _LUX_FULL_KEY, 2.0) is not None
        assert crossKeyRefusal(str(configPath), _LUX_FULL_KEY, 5.0) is None

    def test_overrideLevelThenTheLuxEndsLeadTheAllowList_minLevelNever(self):
        """Scope fence. MOVED PIN (US-895-b): was test_noKeyJoinsTheAllowListInThisStory.
        MOVED PIN (US-895-c): was test_onlyTheLuxEndsJoinTheAllowList_firstAndInOrder.
        overrideLevel goes FIRST, then luxMin/luxFull (DISPLAY order: brightness,
        auto-dim ends, rotate); minLevel is nobody's -- it is the floor."""
        assert OVERRIDABLE_KEYS[:3] == (_OVERRIDE_KEY, _LUX_MIN_KEY, _LUX_FULL_KEY)
        assert _MIN_LEVEL_KEY not in OVERRIDABLE_KEYS

    @pytest.mark.parametrize("value", [None, 0, 0.0, 0.5, 0.75, 0.8, 1, 1.0])
    def test_overrideLevel_takesNullOrAFiniteNumberInZeroToOne(self, value):
        """US-895-c: null = auto; the minLevel floor is the cross-key rule's."""
        assert validateOverlayValue(_OVERRIDE_KEY, value) == (True, value)

    @pytest.mark.parametrize(
        "value", [-0.01, 1.01, 2, True, False, "0.8", float("inf"), float("nan"), [0.8]]
    )
    def test_overrideLevel_refusesAnythingElse(self, value):
        assert validateOverlayValue(_OVERRIDE_KEY, value) == (False, None)

    def test_boot_handEditedOverrideBelowMinLevel_oneWarningNamingTheRule_noFixedLevel(
        self, tmp_path, caplog
    ):
        """
        Given: config.json minLevel 0.75, config.local.json overrideLevel 0.5
               (hand-edited; the key is overridable now)
        When: the orchestrator's read path loads and validates the config
        Then: it validates (eclipse-obd starts); exactly one WARNING names
              'overrideLevel >= minLevel'; overrideLevel stays null -- no fixed
              brightness (US-895-c validationCriteria 3, real allow-list)
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {_OVERRIDE_KEY: 0.5})

        with caplog.at_level(logging.WARNING):
            config = loadConfigWithSecrets(str(configPath))
        ConfigValidator(requiredKeys=[])._validateDisplayAutoDim(config)

        assert config["pi"]["display"]["autoDim"]["overrideLevel"] is None
        warnings = _seamWarnings(caplog)
        assert len(warnings) == 1
        assert _OVERRIDE_KEY in warnings[0]
        assert "overrideLevel >= minLevel" in warnings[0]

    def test_boot_overrideAtOrAboveMinLevel_isApplied(self, tmp_path):
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {_OVERRIDE_KEY: 0.8})

        config = loadConfigWithSecrets(str(configPath))

        assert config["pi"]["display"]["autoDim"]["overrideLevel"] == 0.8

    @pytest.mark.parametrize("value", [0, -1, 0.0, True, "5", None, float("inf"), float("nan")])
    def test_luxEnds_takeOnlyAFinitePositiveNumber(self, value):
        for key in (_LUX_MIN_KEY, _LUX_FULL_KEY):
            assert validateOverlayValue(key, value) == (False, None), (key, value)

    @pytest.mark.parametrize("value", [1, 3.4, 1000])
    def test_luxEnds_acceptAPositiveNumber(self, value):
        for key in (_LUX_MIN_KEY, _LUX_FULL_KEY):
            assert validateOverlayValue(key, value) == (True, value)


class TestLoadOverlay:
    """Reading the overlay file is fail-safe -- never crashes a consumer."""

    def test_loadOverlay_absentFile_returnsEmpty(self, tmp_path: Path):
        """
        Given: no overlay file on disk (the shipped state)
        When: loadOverlay() reads it
        Then: an empty overlay is returned -- config.json defaults stand
        """
        assert loadOverlay(str(tmp_path / "config.local.json")) == {}

    def test_loadOverlay_malformedJson_returnsEmpty(self, tmp_path: Path):
        """
        Given: a truncated/corrupt overlay (interrupted write, bad edit)
        When: loadOverlay() reads it
        Then: an empty overlay is returned -- never a partial guess
        """
        path = tmp_path / "config.local.json"
        path.write_text('{"pi.calibration.mode": tr', encoding="utf-8")

        assert loadOverlay(str(path)) == {}

    def test_loadOverlay_nonObjectJson_returnsEmpty(self, tmp_path: Path):
        """
        Given: an overlay whose top level is not an object
        When: loadOverlay() reads it
        Then: an empty overlay is returned
        """
        path = tmp_path / "config.local.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        assert loadOverlay(str(path)) == {}

    def test_overlayPathFor_resolvesBesideConfigJson(self, tmp_path: Path):
        """
        Given: a path to config.json
        When: overlayPathFor() derives the overlay path
        Then: it is the sibling config.local.json (deterministic, like .env)
        """
        path = Path(overlayPathFor(str(tmp_path / "config.json")))

        assert path.parent == tmp_path
        assert path.name == "config.local.json"


class TestBothReadPathsUseTheSharedResolver:
    """A-4 anti-divergence: every consumer sees ONE effective config."""

    def test_loadConfigWithSecrets_appliesOverlay(self, tmp_path: Path):
        """
        Given: an overlay overriding autoRotateS + power mode
        When: the ORCHESTRATOR read path loads the config
        Then: the effective values are the overlay's
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(
            configPath,
            {"pi.display.carousel.autoRotateS": 0, "pi.calibration.mode": True},
        )

        config = loadConfigWithSecrets(str(configPath))

        assert config["pi"]["display"]["carousel"]["autoRotateS"] == 0
        assert config["pi"]["calibration"]["mode"] is True

    def test_loadDisplayCarouselConfig_appliesOverlay(self, tmp_path: Path):
        """
        Given: an overlay overriding autoRotateS
        When: the STATE SERVER read path loads pi.display.carousel
        Then: the effective value is the overlay's
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {"pi.display.carousel.autoRotateS": 0})

        carousel = loadDisplayCarouselConfig(str(configPath))

        assert carousel is not None
        assert carousel["autoRotateS"] == 0

    @pytest.mark.parametrize("override", [0, 8, 20])
    def test_bothReadPaths_agreeOnEffectiveAutoRotateS(
        self, tmp_path: Path, override: int
    ):
        """
        Given: one overlay and the two independent config readers
        When: each resolves pi.display.carousel.autoRotateS
        Then: they return the IDENTICAL value -- the A-4 divergence this story
              exists to prevent. Either reader skipping the shared resolver
              fails HERE, not only in its own single-reader test.
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {"pi.display.carousel.autoRotateS": override})

        fromOrchestrator = loadConfigWithSecrets(str(configPath))["pi"]["display"][
            "carousel"
        ]["autoRotateS"]
        fromStateServer = loadDisplayCarouselConfig(str(configPath))["autoRotateS"]

        assert fromOrchestrator == fromStateServer == override

    def test_bothReadPaths_agreeWhenOverlayAbsent(self, tmp_path: Path):
        """
        Given: NO overlay file (the shipped state)
        When: both readers resolve autoRotateS
        Then: both return the config.json default
        """
        configPath = _writeConfig(tmp_path)

        fromOrchestrator = loadConfigWithSecrets(str(configPath))["pi"]["display"][
            "carousel"
        ]["autoRotateS"]
        fromStateServer = loadDisplayCarouselConfig(str(configPath))["autoRotateS"]

        assert fromOrchestrator == fromStateServer == 8

    def test_bothReadPaths_agreeOnRejectingAnOutOfAllowListKey(self, tmp_path: Path):
        """
        Given: an overlay carrying an out-of-allow-list key
        When: both readers resolve the config
        Then: neither applies it -- the gate is in the shared seam, not per-reader
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(
            configPath,
            {"pi.display.carousel.resumeIdleS": 999},
        )

        fromOrchestrator = loadConfigWithSecrets(str(configPath))["pi"]["display"][
            "carousel"
        ]["resumeIdleS"]
        fromStateServer = loadDisplayCarouselConfig(str(configPath))["resumeIdleS"]

        assert fromOrchestrator == fromStateServer == 45

    def test_applyConfigOverlay_isTheSeamBothReadersShare(self, tmp_path: Path):
        """
        Given: the seam helper the two readers call
        When: it is applied to a raw-loaded config
        Then: it produces the same effective config the readers return
        """
        configPath = _writeConfig(tmp_path)
        _writeOverlay(configPath, {"pi.calibration.mode": True})
        raw = json.loads(configPath.read_text(encoding="utf-8"))

        effective = applyConfigOverlay(raw, str(configPath))

        assert effective["pi"]["calibration"]["mode"] is True
        assert (
            loadConfigWithSecrets(str(configPath))["pi"]["calibration"]["mode"]
            == effective["pi"]["calibration"]["mode"]
        )


def _commandBlock(text: str, startMarker: str, endMarker: str) -> str:
    """Slice one shell command out of deploy-pi.sh by literal markers.

    Splitting on a bare word ("else", "! -name") picks up the PROSE above the
    code -- deploy-pi.sh comments quote its own flags. Anchor on the command
    itself instead.
    """
    i = text.index(startMarker)
    j = text.index(endMarker, i)
    return text[i : j + len(endMarker)]


def _withoutComments(text: str) -> str:
    """Blank out whole-line bash comments, preserving line structure.

    Same reason as _commandBlock above, in the other direction: deploy-pi.sh
    DOCUMENTS `--delete-excluded` in order to ban it (US-553), so a raw substring
    scan is satisfied -- or, as here, defeated -- by the prose that explains the
    rule. Match the code. Mirrors the sibling guard in
    tests/deploy/test_stale_bytecode_purge.py, which is comment-stripped.
    """
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


class TestOverlayDurability:
    """The overlay must survive a deploy and never reach git."""

    def test_deployPiSh_rsyncCannotDeleteTheOverlay(self):
        """
        Given: the rsync sync path runs --delete against a WHITELIST (2026-08-25)
        When: its filter rules are read
        Then: the overlay is not named by any --include, and the catch-all
              --exclude=* therefore excludes it -- and rsync's --delete spares
              excluded files, so the operator's settings survive.

        This replaces an assertion on --exclude='config.local.json'. That literal
        rule is gone because the blacklist is gone; the PROTECTION is not gone,
        it moved to the catch-all. Verified empirically before this test was
        rewritten: a real rsync -a --delete with these filters left .env,
        config.local.json and data/ untouched while still deleting a stale
        shipped module.
        """
        text = DEPLOY_PI_SH.read_text(encoding="utf-8")
        rsyncBlock = _commandBlock(text, "        rsync \\", '"${PI_USER}@${PI_HOST}:${PI_PATH}/"')

        assert "--include=config.local.json" not in rsyncBlock
        assert "--exclude=*" in rsyncBlock

    def test_deployPiSh_rsyncDoesNotUseDeleteExcluded(self):
        """
        Given: the overlay survives only because --delete spares EXCLUDED files
        When: the rsync flags are read
        Then: --delete-excluded is absent.

        This is the whole load-bearing guard. --delete-excluded is a one-word
        addition that reverses the exclusion's protective meaning and would wipe
        config.local.json, .env and data/ off the car on the next deploy, with
        nothing in the output to say so. Under the old blacklist this flag was
        equally fatal and equally unguarded.
        """
        code = _withoutComments(DEPLOY_PI_SH.read_text(encoding="utf-8"))

        assert "--delete-excluded" not in code

    def test_deployPiSh_tarFallbackDoesNotShipTheOverlay(self):
        """
        Given: the tar fallback ships an explicit FILE LIST (2026-08-25)
        When: that list is read
        Then: the overlay is not in it -- so it is never overwritten by the
              tarball. (The wipe that runs first is guarded separately, by
              test_deployPiSh_tarFallbackWipePreservesTheOverlay below, which is
              the assertion that actually keeps the file alive.)
        """
        text = DEPLOY_PI_SH.read_text(encoding="utf-8")
        tarFileList = _commandBlock(text, '( cd "$REPO_ROOT" && tar -cz', "./deploy )")

        assert "config.local.json" not in tarFileList

    def test_deployPiSh_tarFallbackWipePreservesTheOverlay(self):
        """
        Given: the tar fallback wipes the remote tree before extracting
        When: its preserve list is read
        Then: the overlay is preserved -- excluding it from the TARBALL alone
              would still let the wipe delete the operator's settings.
        """
        text = DEPLOY_PI_SH.read_text(encoding="utf-8")

        assert "! -name 'config.local.json'" in text

    def test_gitignore_ignoresTheOverlay(self):
        """
        Given: the overlay is Pi-local operator state, not shipped config
        When: .gitignore is read
        Then: the overlay is ignored
        """
        lines = {
            line.strip() for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        }

        assert "config.local.json" in lines
