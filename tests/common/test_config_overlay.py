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
# ================================================================================
################################################################################

"""Tests for the F-126 Pi-local config overlay (US-530).

Overlay contract under test:

* The overlay is a FLAT dot-path map (``{"pi.power.mode": "wall"}``) stored
  beside config.json. Flat keys make the allow-list a literal key comparison at
  BOTH the read gate (here) and the US-531 write gate -- defense in depth.
* Effective value = allow-listed overlay override ELSE the config.json default.
* Honest-instrument: a malformed/absent overlay, an out-of-allow-list key, or a
  wrong-typed value resolves to the shipped default -- never a guessed value.
  ``pi.power.mode`` is the one coercion: an invalid mode resolves to ``unknown``
  (never a confident wrong mode).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from common.config.overlay import (
    OVERRIDABLE_KEYS,
    applyConfigOverlay,
    loadOverlay,
    overlayPathFor,
    resolveEffectiveConfig,
    validateOverlayValue,
)
from common.config.secrets_loader import loadConfigWithSecrets
from pi.splash.states_http_server import loadDisplayCarouselConfig

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_PI_SH = REPO_ROOT / "deploy" / "deploy-pi.sh"
GITIGNORE = REPO_ROOT / ".gitignore"


def _writeConfig(tmp: Path, **overrides) -> Path:
    """Write a minimal tier-shaped config.json carrying the 5 Slice-1 keys."""
    config = {
        "protocolVersion": "1.0.0",
        "pi": {
            "display": {"carousel": {"autoRotateS": 8, "resumeIdleS": 45}},
            "power": {"mode": "unknown"},
            "alerts": {"audioAlerts": False},
            "calibration": {"mode": False},
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
        base = {"pi": {"power": {"mode": "unknown"}, "alerts": {"audioAlerts": False}}}

        effective = resolveEffectiveConfig(base, {})

        assert effective["pi"]["power"]["mode"] == "unknown"
        assert effective["pi"]["alerts"]["audioAlerts"] is False

    def test_resolveEffectiveConfig_doesNotMutateBase(self):
        """
        Given: a base config that a caller may reuse
        When: resolveEffectiveConfig() applies an override
        Then: the base dict is untouched (deep copy, not in-place mutation)
        """
        base = {"pi": {"power": {"mode": "unknown"}}}

        effective = resolveEffectiveConfig(base, {"pi.power.mode": "wall"})

        assert effective["pi"]["power"]["mode"] == "wall"
        assert base["pi"]["power"]["mode"] == "unknown"

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
        base = {"pi": {"power": {"mode": "unknown"}}}

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

    @pytest.mark.parametrize("mode", ["car", "wall", "unknown"])
    def test_resolveEffectiveConfig_validPowerMode_applied(self, mode: str):
        """
        Given: an overlay power mode inside {car, wall, unknown}
        When: resolveEffectiveConfig() merges it
        Then: the mode is applied verbatim
        """
        base = {"pi": {"power": {"mode": "unknown"}}}

        effective = resolveEffectiveConfig(base, {"pi.power.mode": mode})

        assert effective["pi"]["power"]["mode"] == mode

    @pytest.mark.parametrize("bogus", ["CAR", "bench", "", 3, None, True])
    def test_resolveEffectiveConfig_invalidPowerMode_resolvesToUnknown(self, bogus):
        """
        Given: an overlay power mode outside {car, wall, unknown}
        When: resolveEffectiveConfig() merges it
        Then: the mode is `unknown` -- honest-unknown, NEVER a confident wrong mode
        """
        base = {"pi": {"power": {"mode": "car"}}}

        effective = resolveEffectiveConfig(base, {"pi.power.mode": bogus})

        assert effective["pi"]["power"]["mode"] == "unknown"

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
                "power": {"mode": "unknown"},
                "alerts": {"audioAlerts": False},
            }
        }

        effective = resolveEffectiveConfig(
            base,
            {"pi.power.mode": "wall", "pi.alerts.audioAlerts": True},
            allowlist=("pi.power.mode",),
        )

        assert effective["pi"]["power"]["mode"] == "wall"
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
        assert set(OVERRIDABLE_KEYS) == {
            "pi.display.carousel.autoRotateS",
            "pi.power.mode",
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
        path.write_text('{"pi.power.mode": "wa', encoding="utf-8")

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
            {"pi.display.carousel.autoRotateS": 0, "pi.power.mode": "wall"},
        )

        config = loadConfigWithSecrets(str(configPath))

        assert config["pi"]["display"]["carousel"]["autoRotateS"] == 0
        assert config["pi"]["power"]["mode"] == "wall"

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
        _writeOverlay(configPath, {"pi.power.mode": "car"})
        raw = json.loads(configPath.read_text(encoding="utf-8"))

        effective = applyConfigOverlay(raw, str(configPath))

        assert effective["pi"]["power"]["mode"] == "car"
        assert (
            loadConfigWithSecrets(str(configPath))["pi"]["power"]["mode"]
            == effective["pi"]["power"]["mode"]
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
