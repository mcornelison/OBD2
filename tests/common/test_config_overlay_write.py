################################################################################
# File Name: test_config_overlay_write.py
# Purpose/Description: F-126 (US-531) tests for the WRITE side of the Pi-local
#   config overlay -- the atomic writer + the effective-value re-read that back
#   the token-gated settings endpoint. US-530 built the read seam; this covers
#   writeOverlayValue (validate -> merge -> temp+rename) and readEffectiveValue
#   (re-resolve from disk through the SAME shared seam, so the endpoint can
#   return the REAL stored value instead of echoing the request).
#
#   Tests assert: the write gate is the US-530 allow-list (no second gate),
#   an atomic replace failure leaves the PRIOR overlay byte-intact, unrelated
#   overlay keys survive a write, and readEffectiveValue reports what the
#   readers will actually see -- not what was asked for.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Ralph (Rex)  | Initial implementation (US-531 overlay writer).
# ================================================================================
################################################################################

"""Tests for the US-531 overlay write helpers in ``common.config.overlay``."""

import json
import os
from pathlib import Path

import pytest

from common.config import overlay as overlayModule
from common.config.overlay import (
    OVERLAY_FILENAME,
    getDotPath,
    loadOverlay,
    overlayPathFor,
    readEffectiveValue,
    writeOverlayValue,
)

_AUTO_ROTATE_KEY = "pi.display.carousel.autoRotateS"
# US-668: this was the power-mode key. These tests are about OVERLAY behaviour
# -- write-gate rejection, verbatim storage, merge-not-clobber, atomic rollback,
# dot-path traversal -- and power was only ever the example. Re-pointed at a
# surviving allow-listed key so the coverage outlives the removal.
_CALIB_KEY = "pi.calibration.mode"

# A base config.json whose defaults DIFFER from every value the tests write, so
# no assertion can pass by accidentally matching the fallback (US-530 lesson:
# an expected value equal to the default proves nothing).
_BASE_CONFIG = {
    "deviceId": "test-pi",
    "pi": {
        "display": {"carousel": {"autoRotateS": 8}},
        "power": {"mode": "car"},
        "alerts": {"audioAlerts": False},
        "calibration": {"mode": False},
        "analysis": {"triggerAfterDrive": False},
    },
}


@pytest.fixture
def configPath(tmp_path: Path) -> str:
    """A real config.json on disk plus its (absent) sibling overlay path."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_BASE_CONFIG), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# writeOverlayValue -- validation gate
# ---------------------------------------------------------------------------


def test_writeOverlayValue_allowListedKey_persistsToOverlayFile(tmp_path):
    """
    Given: an absent overlay beside config.json
    When: an allow-listed, well-typed value is written
    Then: the overlay file exists and carries the flat dot-path entry
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0) is True

    assert loadOverlay(overlayPath) == {_AUTO_ROTATE_KEY: 0}


def test_writeOverlayValue_outOfAllowListKey_refusedAndNoFileCreated(tmp_path):
    """
    Given: a key that is not on the US-530 Slice-1 allow-list
    When: a write is attempted
    Then: it is refused and NO overlay file is created (no write side effect)
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, "pi.obd.port", "/dev/rfcomm0") is False

    assert not Path(overlayPath).exists()


def test_writeOverlayValue_wrongTypedValue_refusedAndNoFileCreated(tmp_path):
    """
    Given: an allow-listed key with a value of the wrong type
    When: a write is attempted
    Then: it is refused with no file created -- the write gate IS the read gate
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, "fast") is False

    assert not Path(overlayPath).exists()


def test_writeOverlayValue_boolRejectedForNumericKey(tmp_path):
    """
    Given: True (which Python treats as 1) for the numeric autoRotateS key
    When: a write is attempted
    Then: it is refused -- bool must not sneak through the numeric check
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, True) is False

    assert not Path(overlayPath).exists()


def test_writeOverlayValue_invalidPowerMode_refusedAndNotCoercedOnDisk(tmp_path):
    """
    Given: a value that fails the key's validator
    When: a write is attempted
    Then: it is refused and nothing is stored -- the write gate rejects rather
          than silently persisting the read seam's 'unknown' coercion
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _CALIB_KEY, "banana") is False

    assert not Path(overlayPath).exists()


def test_writeOverlayValue_validPowerMode_persists(tmp_path):
    """
    Given: an exact member of the power-mode enum
    When: it is written
    Then: it is stored verbatim
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _CALIB_KEY, True) is True

    assert loadOverlay(overlayPath)[_CALIB_KEY] is True


# ---------------------------------------------------------------------------
# writeOverlayValue -- merge + durability
# ---------------------------------------------------------------------------


def test_writeOverlayValue_preservesUnrelatedExistingKeys(tmp_path):
    """
    Given: an overlay already holding another operator setting
    When: a different allow-listed key is written
    Then: BOTH entries survive -- a write merges, it never clobbers the file
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)
    writeOverlayValue(overlayPath, _CALIB_KEY, True)

    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0)

    stored = loadOverlay(overlayPath)
    assert stored[_CALIB_KEY] is True
    assert stored[_AUTO_ROTATE_KEY] == 0


def test_writeOverlayValue_overwritesSameKey(tmp_path):
    """
    Given: an overlay already overriding autoRotateS
    When: the same key is written again with a new value
    Then: the newest value wins (one entry, not a duplicate)
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)
    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 20)

    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0)

    assert loadOverlay(overlayPath) == {_AUTO_ROTATE_KEY: 0}


def test_writeOverlayValue_replaceFailure_leavesPriorOverlayIntact(tmp_path, monkeypatch):
    """
    Given: an overlay holding a good value, and a failing atomic replace
    When: a new write is attempted
    Then: False is returned AND the prior overlay is byte-identical -- this is
          what temp+rename buys; a partial write must never corrupt settings
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)
    writeOverlayValue(overlayPath, _CALIB_KEY, True)
    before = Path(overlayPath).read_bytes()

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(overlayModule.os, "replace", boom)

    assert writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0) is False

    assert Path(overlayPath).read_bytes() == before


def test_writeOverlayValue_replaceFailure_leavesNoTempFileBehind(tmp_path, monkeypatch):
    """
    Given: a failing atomic replace
    When: a write is attempted
    Then: the scratch temp file is cleaned up -- a failed save must not litter
          the Pi with partial overlays that a later glob could mistake for real
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(overlayModule.os, "replace", boom)
    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0)

    assert list(tmp_path.iterdir()) == []


def test_writeOverlayValue_unwritableDirectory_returnsFalse(tmp_path):
    """
    Given: an overlay path inside a directory that does not exist
    When: a write is attempted
    Then: False is returned rather than an exception escaping to the caller
    """
    overlayPath = str(tmp_path / "no-such-dir" / OVERLAY_FILENAME)

    assert writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0) is False


def test_writeOverlayValue_malformedExistingOverlay_isReplacedNotAppendedTo(tmp_path):
    """
    Given: an existing overlay file that is not valid JSON (readers ignore it)
    When: an allow-listed value is written
    Then: the file becomes a well-formed overlay holding the new entry -- the
          write repairs rather than propagating a file nothing could honour
    """
    overlayPath = tmp_path / OVERLAY_FILENAME
    overlayPath.write_text("{not json", encoding="utf-8")

    assert writeOverlayValue(str(overlayPath), _AUTO_ROTATE_KEY, 0) is True

    assert loadOverlay(str(overlayPath)) == {_AUTO_ROTATE_KEY: 0}


def test_writeOverlayValue_writesValidJsonOnDisk(tmp_path):
    """
    Given: a written overlay
    When: the raw bytes are parsed directly (not via the fail-safe loader)
    Then: they are valid JSON -- loadOverlay's {} fallback cannot mask a
          malformed writer, so assert the disk format itself
    """
    overlayPath = tmp_path / OVERLAY_FILENAME
    writeOverlayValue(str(overlayPath), _AUTO_ROTATE_KEY, 0)

    assert json.loads(overlayPath.read_text(encoding="utf-8")) == {_AUTO_ROTATE_KEY: 0}


# ---------------------------------------------------------------------------
# getDotPath / readEffectiveValue -- the honest read-back
# ---------------------------------------------------------------------------


def test_getDotPath_presentKey_returnsFoundAndValue():
    """
    Given: a config holding the dot-path
    When: it is read
    Then: (True, value) is returned
    """
    assert getDotPath(_BASE_CONFIG, _AUTO_ROTATE_KEY) == (True, 8)


def test_getDotPath_absentKey_returnsNotFound():
    """
    Given: a config lacking the dot-path
    When: it is read
    Then: (False, None) -- absence is reported, never guessed as a value
    """
    assert getDotPath(_BASE_CONFIG, "pi.nope.missing") == (False, None)


def test_getDotPath_nonDictBranch_returnsNotFound():
    """
    Given: an intermediate path segment that is not a dict
    When: the dot-path is read
    Then: (False, None) rather than a TypeError escaping to the caller
    """
    assert getDotPath({"pi": {"calibration": "car"}}, _CALIB_KEY) == (False, None)


def test_readEffectiveValue_noOverlay_returnsConfigDefault(configPath):
    """
    Given: no overlay beside config.json (the shipped state)
    When: the effective value is read
    Then: the config.json default is returned
    """
    assert readEffectiveValue(configPath, _AUTO_ROTATE_KEY) == (True, 8)


def test_readEffectiveValue_afterWrite_returnsOverriddenValue(configPath):
    """
    Given: an overlay override written beside config.json
    When: the effective value is re-read from disk
    Then: the OVERRIDE is returned -- this is the read-back that lets the
          endpoint report the real stored value instead of echoing the request
    """
    writeOverlayValue(overlayPathFor(configPath), _AUTO_ROTATE_KEY, 0)

    assert readEffectiveValue(configPath, _AUTO_ROTATE_KEY) == (True, 0)


# US-668 deleted test_readEffectiveValue_..._coercingInvalidPowerMode.
# pi.power.mode was the ONLY coercion in the overlay -- the read seam resolved a
# corrupt mode to "unknown" rather than to the shipped default. With the key gone
# that branch is gone, so the test is deleted rather than re-pointed: no surviving
# key exercises it, and a test aimed at a code path that no longer exists is worse
# than no test.


def test_readEffectiveValue_unreadableConfig_returnsNotFound(tmp_path):
    """
    Given: no config.json at the given path
    When: the effective value is read
    Then: (False, None) -- never a fabricated value
    """
    assert readEffectiveValue(str(tmp_path / "missing.json"), _AUTO_ROTATE_KEY) == (
        False,
        None,
    )


def test_readEffectiveValue_malformedConfig_returnsNotFound(tmp_path):
    """
    Given: a config.json that is not valid JSON
    When: the effective value is read
    Then: (False, None) rather than an exception reaching the HTTP layer
    """
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")

    assert readEffectiveValue(str(path), _AUTO_ROTATE_KEY) == (False, None)


def test_writeThenRead_roundTripsAutoRotateSBothWays(configPath):
    """
    Given: the auto-rotate off/on contract (0 = off, >0 = on; US-530 GAP 3a)
    When: 0 and then a real interval are written
    Then: each round-trips through the overlay to the effective value
    """
    overlayPath = overlayPathFor(configPath)

    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0)
    assert readEffectiveValue(configPath, _AUTO_ROTATE_KEY) == (True, 0)

    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 20)
    assert readEffectiveValue(configPath, _AUTO_ROTATE_KEY) == (True, 20)


def test_writeOverlayValue_neverTouchesConfigJson(configPath):
    """
    Given: the US-530 contract that nothing writes config.json at runtime
    When: an overlay value is written
    Then: config.json is byte-identical -- the shipped default stays read-only
    """
    before = Path(configPath).read_bytes()

    writeOverlayValue(overlayPathFor(configPath), _AUTO_ROTATE_KEY, 0)

    assert Path(configPath).read_bytes() == before


def test_overlayWriterUsesOsReplace_notATruncatingWrite(tmp_path, monkeypatch):
    """
    Given: the atomicity requirement (temp + rename, never write-in-place)
    When: a value is written
    Then: os.replace is what lands the file -- pinning the MECHANISM, since a
          truncating open() of the real path would pass every other test here
    """
    overlayPath = str(tmp_path / OVERLAY_FILENAME)
    seen = {}
    realReplace = os.replace

    def spy(src, dst):
        seen["args"] = (str(src), str(dst))
        return realReplace(src, dst)

    monkeypatch.setattr(overlayModule.os, "replace", spy)
    writeOverlayValue(overlayPath, _AUTO_ROTATE_KEY, 0)

    assert seen["args"][1] == overlayPath
    assert seen["args"][0] != overlayPath
