################################################################################
# File Name: test_local_zone_config.py
# Purpose/Description: US-809-0 -- pi.time.localZone is a DECLARED IANA zone in
#                      config.json and validator DEFAULTS; an unknown zone is
#                      REJECTED naming the key; a missing or invalid zone makes
#                      conversion REFUSE rather than guess the host zone; and
#                      the key ends this story with exactly one consumer.
# Author: Ralph (US-809-0)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-0) | Initial -- declaration, rejection, refusal,
#               |                  | single-consumer guard.
# ================================================================================
################################################################################
"""Tests for the declared local timezone (US-809-0).

WHAT THIS KEY IS FOR, so a future reader does not hunt a bug that does not
exist: ``pi.time.localZone`` PREVENTS A FUTURE DIVERGENCE -- it does not fix a
present one. Measured on chi-eclipse-01 2026-09-23: it already reads
America/Chicago and keeps its RTC in UTC. Today the zone is an undeclared OS
setting that happens to be right; a reimage or a ``raspi-config`` change would
shift every converted timestamp with no code change and no test failure.
Declaring it makes that a config diff instead of a silent data corruption.

The same reading reported ``System clock synchronized: no`` (NTP active), which
the story text gave as synchronised. Recorded because it is the clockSynced
half of A-double-prime, not because it affects this key: a declared zone does
not make a clock trustworthy.

It also does NOT replace the A-54 canary. Config declares WHICH zone naive
values are expressed in; it cannot declare that a producer COMPLIES. A producer
emitting naive-UTC still has ``tzinfo`` None, still takes the naive branch and
is still shifted. Config supplies the value; the canary enforces compliance.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.common.config.validator import ConfigValidationError, ConfigValidator
from src.common.time.helper import (
    LOCAL_ZONE_CONFIG_KEY,
    localNaiveToCanonicalIso,
    resolveLocalZone,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The zone the CIO ratified on 2026-09-23. Not derived, not host-seeded.
_RATIFIED_ZONE = 'America/Chicago'


def _baseCfg(time: dict | None = None) -> dict:
    """A minimal valid config, optionally carrying a pi.time section."""
    return {
        "protocolVersion": "1",
        "schemaVersion": "1",
        "deviceId": "d",
        "pi": {} if time is None else {"time": time},
        "server": {},
    }


class TestTheZoneIsDeclared:
    """Acceptance 1 -- the key exists and names a real IANA zone."""

    def test_validate_absentKey_defaultsToTheRatifiedZone(self) -> None:
        """
        Given: a config with no pi.time section
        When: it is validated
        Then: pi.time.localZone defaults to the ratified America/Chicago
        """
        cfg = ConfigValidator().validate(_baseCfg())

        assert cfg["pi"]["time"]["localZone"] == _RATIFIED_ZONE

    def test_configJson_carriesTheKey_andItConstructs(self) -> None:
        """
        Given: the shipped config.json
        When: pi.time.localZone is read and handed to ZoneInfo
        Then: it is the ratified zone and it constructs without raising
        """
        raw = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        declared = raw["pi"]["time"]["localZone"]

        assert declared == _RATIFIED_ZONE
        assert ZoneInfo(declared) is not None


class TestAnUnknownZoneIsRejected:
    """Acceptance 2 -- the validator refuses a zone that is not in the database."""

    def test_validate_unknownZone_raisesNamingTheKey(self) -> None:
        """
        Given: a config declaring the zone 'Mars/Olympus'
        When: it is validated
        Then: validation fails and the message names pi.time.localZone
        """
        cfg = _baseCfg({"localZone": "Mars/Olympus"})

        with pytest.raises(ConfigValidationError) as err:
            ConfigValidator().validate(cfg)

        assert LOCAL_ZONE_CONFIG_KEY in str(err.value)

    def test_validate_malformedZone_raisesNamingTheKey(self) -> None:
        """
        Given: a config whose zone is malformed rather than merely unknown
        When: it is validated
        Then: it is rejected the same way

        ZoneInfo raises ZoneInfoNotFoundError (a KeyError) for an unknown key
        but ValueError for a malformed one. Both are rejections; catching only
        the first would let '../etc/passwd' through the validator.
        """
        cfg = _baseCfg({"localZone": "../etc/passwd"})

        with pytest.raises(ConfigValidationError) as err:
            ConfigValidator().validate(cfg)

        assert LOCAL_ZONE_CONFIG_KEY in str(err.value)


class TestConversionRefusesRatherThanGuesses:
    """Acceptance 3 -- no timestamp is produced when the zone is not declared."""

    def test_resolveLocalZone_declaredZone_returnsThatZone(self) -> None:
        """
        Given: a config declaring the ratified zone
        When: the zone is resolved
        Then: the returned ZoneInfo is that zone
        """
        cfg = _baseCfg({"localZone": _RATIFIED_ZONE})

        assert resolveLocalZone(cfg) == ZoneInfo(_RATIFIED_ZONE)

    @pytest.mark.parametrize(
        "time",
        [None, {}, {"localZone": None}, {"localZone": ""}, {"localZone": "Mars/Olympus"}],
        ids=["noSection", "emptySection", "null", "empty", "unknown"],
    )
    def test_resolveLocalZone_absentOrInvalid_refuses(self, time: dict | None) -> None:
        """
        Given: a config whose zone is absent, empty or not a real zone
        When: the zone is resolved
        Then: it raises ValueError naming the key -- it does not return a zone
        """
        with pytest.raises(ValueError) as err:
            resolveLocalZone(_baseCfg(time))

        assert LOCAL_ZONE_CONFIG_KEY in str(err.value)

    @pytest.mark.parametrize(
        "time",
        [None, {"localZone": None}, {"localZone": "Mars/Olympus"}],
        ids=["noSection", "null", "unknown"],
    )
    def test_localNaiveToCanonicalIso_undeclaredZone_producesNoTimestamp(
        self, time: dict | None
    ) -> None:
        """
        Given: a naive datetime and a config with no usable zone
        When: conversion is attempted
        Then: it raises and NO timestamp is returned

        This is the whole point of the key. Guessing the host zone is the
        defect it exists to remove, so the failure mode must be a refusal and
        not a value.
        """
        naive = datetime(2026, 9, 23, 12, 0, 0)

        with pytest.raises(ValueError) as err:
            localNaiveToCanonicalIso(naive, _baseCfg(time))

        assert LOCAL_ZONE_CONFIG_KEY in str(err.value)

    def test_localNaiveToCanonicalIso_neverFallsBackToTheHostZone(self) -> None:
        """
        Given: a naive datetime and a config with no declared zone
        When: conversion is attempted
        Then: it refuses -- and in particular does NOT return what the host
              zone would have produced

        A silent host fallback passes a 'did it raise' test on a machine whose
        host zone happens to be right. This asserts the host's own answer is
        not produced, so the test still fails on a America/Chicago laptop.
        """
        naive = datetime(2026, 9, 23, 12, 0, 0)
        hostWouldSay = naive.astimezone().strftime('%Y-%m-%dT%H:%M:%SZ')

        with pytest.raises(ValueError):
            produced = localNaiveToCanonicalIso(naive, _baseCfg(None))
            assert produced != hostWouldSay, "fell back to the host zone"

    @pytest.mark.parametrize(
        ("naive", "expected"),
        [
            (datetime(2026, 9, 23, 12, 0, 0), "2026-09-23T17:00:00Z"),
            (datetime(2026, 1, 15, 12, 0, 0), "2026-01-15T18:00:00Z"),
        ],
        ids=["CDT-summer", "CST-winter"],
    )
    def test_localNaiveToCanonicalIso_declaredZone_appliesTheRealOffset(
        self, naive: datetime, expected: str
    ) -> None:
        """
        Given: a naive local datetime either side of the DST boundary
        When: it is converted through the declared zone
        Then: the canonical UTC string carries the offset for THAT date

        The pair is the point: -5 in September and -6 in January. A fixed
        offset hardcoded anywhere would pass one of these and fail the other.
        """
        cfg = _baseCfg({"localZone": _RATIFIED_ZONE})

        assert localNaiveToCanonicalIso(naive, cfg) == expected


class TestTheKeyHasExactlyOneConsumer:
    """Acceptance 4 -- a config key with no reader is an inert field (A-50).

    'Reader' here means a site that pulls the VALUE OUT of a config dict in
    order to use it. The declaration in the DEFAULTS registry and the
    validator's own rejection check are not consumers -- the validator must
    read the value to reject it, and a story that forbade that would forbid
    acceptance 2. So the guard is: exactly one module OUTSIDE
    src/common/config/ consumes the key, and it is the time helper.
    """

    def test_exactlyOneModuleOutsideConfigConsumesTheKey(self) -> None:
        """
        Given: the src/ tree
        When: every module naming the key IN EXECUTABLE CODE is collected
        Then: exactly one lies outside src/common/config, and it is the helper

        DOCSTRINGS ARE STRIPPED, and that is not a convenience. US-809-c gave
        realtime.py a docstring that names ``pi.time.localZone`` to explain
        where its conversion gets the zone -- documentation of a call it makes
        THROUGH the helper, not a second read of the key. A text scan counts
        that as a consumer and goes red on a tree that is correct, which is how
        a guard earns its deletion. The same correction US-773 needed.
        """
        srcRoot = _REPO_ROOT / "src"
        consumers = sorted(
            path.relative_to(_REPO_ROOT).as_posix()
            for path in srcRoot.rglob("*.py")
            if _namesKeyInCode(path)
            and "common/config/" not in path.relative_to(_REPO_ROOT).as_posix()
        )

        assert consumers == ["src/common/time/helper.py"], (
            f"pi.time.localZone must have exactly one consumer; found {consumers}"
        )

    def test_theConsumerActuallyReadsIt_notJustNamesIt(self) -> None:
        """
        Given: the time helper
        When: its AST is walked for the resolver
        Then: resolveLocalZone is defined there and the key constant is used

        Without this, the guard above is satisfied by a module that merely
        mentions the key in a comment -- an inert field with a decorative
        reader, which is the A-50 defect wearing the shape of its own fix.
        """
        helper = _REPO_ROOT / "src" / "common" / "time" / "helper.py"
        tree = ast.parse(helper.read_text(encoding="utf-8"))

        functions = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }

        assert "resolveLocalZone" in functions
        assert LOCAL_ZONE_CONFIG_KEY == "pi.time.localZone"


def _namesKeyInCode(path: Path) -> bool:
    """True when the module names the zone key outside a docstring.

    Walks the AST and ignores every string that is a module, class or function
    docstring, so prose about the key is not mistaken for a read of it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "localZone" in node.value
        and id(node) not in docstrings
        for node in ast.walk(tree)
    )
