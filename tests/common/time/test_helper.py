################################################################################
# File Name: test_helper.py
# Purpose/Description: Unit tests for src/common/time/helper.py canonical
#                      timestamp helpers (utcIsoNow, toCanonicalIso).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-202 (TD-027 fix)
# ================================================================================
################################################################################

"""Tests for src.common.time.helper.

Validates the canonical ISO-8601 UTC timestamp format (`%Y-%m-%dT%H:%M:%SZ`)
that every capture-table writer in the Pi tree must use post-US-202.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.common.time.helper import CANONICAL_ISO_REGEX, toCanonicalIso, utcIsoNow

# Canonical regex lives in the module so that tests and production code share
# the same definition of "canonical".
_CANONICAL_RE = re.compile(CANONICAL_ISO_REGEX)


class TestUtcIsoNow:
    """utcIsoNow() — the primary helper for capture-table writers."""

    def test_utcIsoNow_returnsCanonicalFormat(self) -> None:
        """
        Given: the helper is called
        When: the returned string is matched against the canonical regex
        Then: the match succeeds (^YYYY-MM-DDTHH:MM:SSZ$).
        """
        result = utcIsoNow()

        assert _CANONICAL_RE.match(result), (
            f"utcIsoNow() returned {result!r}, which does not match canonical "
            f"ISO-8601 UTC regex {CANONICAL_ISO_REGEX!r}"
        )

    def test_utcIsoNow_endsWithZ(self) -> None:
        assert utcIsoNow().endswith('Z')

    def test_utcIsoNow_hasTSeparator(self) -> None:
        # Position 10 in YYYY-MM-DDTHH:MM:SSZ is the 'T'.
        assert utcIsoNow()[10] == 'T'

    def test_utcIsoNow_parsesAsUtc(self) -> None:
        """
        Given: utcIsoNow() returned string
        When: parsed back as an ISO-8601 timestamp
        Then: the resulting datetime is tz-aware UTC and within 60s of now.
        """
        result = utcIsoNow()

        # strptime doesn't accept 'Z' on older Pythons; normalize to +00:00.
        parsed = datetime.fromisoformat(result.replace('Z', '+00:00'))

        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

        now = datetime.now(UTC)
        assert abs((now - parsed).total_seconds()) < 60

    def test_utcIsoNow_notAffectedByLocalTimezone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: Pi is physically set to America/Chicago (UTC-5/-6)
        When: utcIsoNow() runs
        Then: the hour reflects UTC, NOT local Chicago time.

        Guards against the TD-027 Thread 2 bug where naive `datetime.now()`
        produced local-time strings on the Pi.
        """
        # Freeze "now" to a known UTC moment.  Use a real tz-aware UTC datetime
        # so utcIsoNow() can't be fooled by a local-tz substitute.
        fixedUtc = datetime(2026, 4, 19, 17, 30, 0, tzinfo=UTC)

        class _FakeDatetime:
            @classmethod
            def now(cls, tz: timezone | None = None) -> datetime:
                # Honor the tz argument exactly like real datetime.now.
                if tz is None:
                    return fixedUtc.replace(tzinfo=None)
                return fixedUtc.astimezone(tz)

        import src.common.time.helper as helperModule
        monkeypatch.setattr(helperModule, 'datetime', _FakeDatetime)

        assert utcIsoNow() == '2026-04-19T17:30:00Z'


class TestToCanonicalIso:
    """toCanonicalIso(dt) — the conversion helper for caller-supplied datetimes."""

    def test_toCanonicalIso_acceptsUtcAware(self) -> None:
        dt = datetime(2026, 4, 19, 12, 17, 9, tzinfo=UTC)
        assert toCanonicalIso(dt) == '2026-04-19T12:17:09Z'

    def test_toCanonicalIso_convertsNonUtcAwareToUtc(self) -> None:
        """
        Given: a tz-aware datetime in America/Chicago (UTC-5 in CDT)
        When: toCanonicalIso converts it
        Then: the result is in UTC (hour shifts by +5).
        """
        cdt = timezone(timedelta(hours=-5))
        dt = datetime(2026, 4, 19, 7, 20, 30, tzinfo=cdt)

        assert toCanonicalIso(dt) == '2026-04-19T12:20:30Z'

    def test_toCanonicalIso_rejectsNaiveDatetime(self) -> None:
        """
        Given: a naive datetime (no tzinfo)
        When: toCanonicalIso is called
        Then: ValueError is raised at the boundary.

        This is the guard that enforces the TD-027 invariant: no naive
        datetime may ever end up in a capture-table row.
        """
        naive = datetime(2026, 4, 19, 7, 20, 30)  # no tzinfo

        with pytest.raises(ValueError, match='naive'):
            toCanonicalIso(naive)

    def test_toCanonicalIso_stripsMicrosecondsAndFractional(self) -> None:
        """
        Given: a tz-aware datetime with microseconds
        When: toCanonicalIso converts it
        Then: microseconds are truncated -- the canonical format has
              second-level precision only.
        """
        dt = datetime(2026, 4, 19, 7, 20, 30, 837646, tzinfo=UTC)

        assert toCanonicalIso(dt) == '2026-04-19T07:20:30Z'


class TestHelperIdempotency:
    """utcIsoNow() and toCanonicalIso() produce the same shape for a fixed moment."""

    def test_utcIsoNowAndToCanonicalIsoAgreeOnShape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixedUtc = datetime(2026, 4, 19, 17, 30, 0, tzinfo=UTC)

        class _FakeDatetime:
            @classmethod
            def now(cls, tz: timezone | None = None) -> datetime:
                if tz is None:
                    return fixedUtc.replace(tzinfo=None)
                return fixedUtc.astimezone(tz)

        import src.common.time.helper as helperModule
        monkeypatch.setattr(helperModule, 'datetime', _FakeDatetime)

        viaNow = utcIsoNow()
        viaConversion = toCanonicalIso(fixedUtc)

        assert viaNow == viaConversion
