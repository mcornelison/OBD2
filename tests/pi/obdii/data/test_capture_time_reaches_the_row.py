################################################################################
# File Name: test_capture_time_reaches_the_row.py
# Purpose/Description: US-809-a -- BOTH writers into realtime_data store the
#                      reading's CAPTURE instant, converted against the DECLARED
#                      zone. Fixing one writer would leave the column holding
#                      two different meanings with nothing to tell them apart.
# Author: Ralph (US-809-a)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-a) | Initial -- both writers, declared zone,
#               |                  | already-aware input.
# ================================================================================
################################################################################
"""Capture time reaches the row, in BOTH writers (US-809-a).

Link 3 of the three-link chain. Spec A-double-prime, worked: a reading taken
13:00:00 local and drained 13:00:47 stores capture 18:00:00Z, not 18:00:47Z.
Today those 47 seconds of queueing read as 47 seconds of driving -- a
discontinuous capture rendered as a continuous one.

TWO writers INSERT into realtime_data with the same column list, and both
discarded ``reading.timestamp``. A one-file fix is worse than today: today the
column is uniformly a write time, which is at least one consistent meaning.

WHY THE CONVERSION IS AT THE WRITER and not in the producers: measured
2026-09-23, ``src/pi`` has 107 bare ``datetime.now()`` call sites, most of them
legitimate elapsed-time arithmetic. Converting once at a boundary against a
DECLARED zone is the architecture; sweeping 107 producers is not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.pi.obdii.data.helpers import logReading as helperLogReading
from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.data.types import LoggedReading

# The ratified zone is America/Chicago and the bench runs in it, so a test that
# used it could pass while reading the HOST's zone. Every zone assertion here
# uses a zone the runner is NOT in.
_FOREIGN_ZONE = "Asia/Tokyo"          # UTC+9, no DST
_RATIFIED_ZONE = "America/Chicago"    # UTC-5 on 2026-09-23 (CDT)

_CAPTURED_LOCAL = datetime(2026, 9, 23, 13, 0, 0)


def _cfg(zone: str) -> dict[str, Any]:
    return {"pi": {"time": {"localZone": zone}}}


class _FakeDatabase:
    """ObdDatabase stand-in -- records the INSERT parameter tuples."""

    def __init__(self) -> None:
        self.inserts: list[tuple[Any, ...]] = []

    def connect(self) -> Any:
        outer = self

        class _Cursor:
            def execute(self, sql: str, params: tuple[Any, ...]) -> None:
                outer.inserts.append(params)

        class _Conn:
            def cursor(self) -> _Cursor:
                return _Cursor()

            def __enter__(self) -> _Conn:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

        return _Conn()


def _reading(timestamp: datetime) -> LoggedReading:
    return LoggedReading(
        parameterName="RPM", value=3500.0, timestamp=timestamp,
        unit="rpm", profileId="daily",
    )


def _storedTimestamp(db: _FakeDatabase) -> str:
    """The `timestamp` column is the first bound parameter of the INSERT."""
    assert db.inserts, "no row was inserted"
    return db.inserts[0][0]


# ==============================================================================
# Acceptance 1 -- BOTH writers converted
# ==============================================================================

class TestBothWritersStoreTheCaptureInstant:
    """Each writer is asserted SEPARATELY; a shared helper would hide one."""

    def test_loggerWriter_storesTheReadingsInstant(self) -> None:
        """
        Given: a LoggedReading captured at 13:00 local, logged much later
        When:  ObdDataLogger.logReading writes it
        Then:  the stored timestamp is the CAPTURE instant in UTC

        13:00 America/Chicago on 2026-09-23 is CDT (-5) -> 18:00:00Z.
        """
        db = _FakeDatabase()
        writer = ObdDataLogger(
            connection=None, database=db, profileId="daily",
            config=_cfg(_RATIFIED_ZONE),
        )

        writer.logReading(_reading(_CAPTURED_LOCAL))

        assert _storedTimestamp(db) == "2026-09-23T18:00:00Z"

    def test_helpersWriter_storesTheReadingsInstant(self) -> None:
        """
        Given: the same reading through the SECOND writer
        When:  helpers.logReading writes it
        Then:  the stored timestamp is the same capture instant

        This is the writer Atlas's audit found and the story's first draft
        missed. Same INSERT, same column list, same discard.
        """
        db = _FakeDatabase()

        helperLogReading(db, _reading(_CAPTURED_LOCAL), config=_cfg(_RATIFIED_ZONE))

        assert _storedTimestamp(db) == "2026-09-23T18:00:00Z"

    def test_neitherWriterStoresTheWriteTime(self) -> None:
        """
        Given: a capture instant deliberately far from now
        When:  both writers run
        Then:  neither stores anything resembling the current time

        The capture instant is in the past, so a write-time stamp cannot
        coincide with it. This is the assertion that fails at the branch point.
        """
        nowYear = datetime.now(UTC).strftime("%Y-%m-%d")

        loggerDb = _FakeDatabase()
        ObdDataLogger(
            connection=None, database=loggerDb, profileId="daily",
            config=_cfg(_RATIFIED_ZONE),
        ).logReading(_reading(datetime(2019, 3, 4, 5, 6, 7)))

        helpersDb = _FakeDatabase()
        helperLogReading(
            helpersDb, _reading(datetime(2019, 3, 4, 5, 6, 7)),
            config=_cfg(_RATIFIED_ZONE),
        )

        for db in (loggerDb, helpersDb):
            stored = _storedTimestamp(db)
            assert stored.startswith("2019-03-04"), stored
            assert not stored.startswith(nowYear), "a write time was stored"


# ==============================================================================
# Acceptance 2 -- the DECLARED zone, not the host's
# ==============================================================================

class TestTheDeclaredZoneIsUsed:
    """The story is explicit: a test using the runner's own zone is vacuous."""

    @pytest.mark.parametrize(
        ("zone", "expected"),
        [
            (_RATIFIED_ZONE, "2026-09-23T18:00:00Z"),  # CDT, -5
            (_FOREIGN_ZONE, "2026-09-23T04:00:00Z"),   # JST, +9
        ],
        ids=["ratified", "foreign"],
    )
    def test_loggerWriter_followsTheConfiguredZone(
        self, zone: str, expected: str
    ) -> None:
        """
        Given: the same naive capture instant under two different zones
        When:  the row is written
        Then:  the stored UTC instant differs, following CONFIG

        The pair is the point. The bench runs in America/Chicago, so an
        assertion made only against that zone would pass while the code read
        the host -- exactly the vacuous test the story warns about. Asia/Tokyo
        is +9 and has no DST, so the two answers are 14 hours apart.
        """
        db = _FakeDatabase()
        ObdDataLogger(
            connection=None, database=db, profileId="daily", config=_cfg(zone),
        ).logReading(_reading(_CAPTURED_LOCAL))

        assert _storedTimestamp(db) == expected

    @pytest.mark.parametrize(
        ("zone", "expected"),
        [
            (_RATIFIED_ZONE, "2026-09-23T18:00:00Z"),
            (_FOREIGN_ZONE, "2026-09-23T04:00:00Z"),
        ],
        ids=["ratified", "foreign"],
    )
    def test_helpersWriter_followsTheConfiguredZone(
        self, zone: str, expected: str
    ) -> None:
        db = _FakeDatabase()
        helperLogReading(db, _reading(_CAPTURED_LOCAL), config=_cfg(zone))

        assert _storedTimestamp(db) == expected


# ==============================================================================
# Acceptance 3 -- already-aware input is used as-is
# ==============================================================================

class TestAlreadyAwareInputIsNotShiftedTwice:
    """Both paths, in one class, as the story asks."""

    @pytest.mark.parametrize("writer", ["logger", "helpers"], ids=["logger", "helpers"])
    def test_awareTimestamp_isNotShiftedAgain(self, writer: str) -> None:
        """
        Given: a reading whose timestamp is ALREADY tz-aware UTC
        When:  it is written
        Then:  the stored value is that instant, unshifted

        The bus path produces aware timestamps (US-809-c parses the wire value
        back). Attaching the local zone to an already-aware value would shift
        it a second time -- the value would be wrong by the offset, and it
        would look entirely plausible.
        """
        aware = datetime(2026, 9, 23, 18, 0, 0, tzinfo=UTC)
        db = _FakeDatabase()

        if writer == "logger":
            ObdDataLogger(
                connection=None, database=db, profileId="daily",
                config=_cfg(_FOREIGN_ZONE),
            ).logReading(_reading(aware))
        else:
            helperLogReading(db, _reading(aware), config=_cfg(_FOREIGN_ZONE))

        # The configured zone is +9; if it were applied, this would read 09:00Z.
        assert _storedTimestamp(db) == "2026-09-23T18:00:00Z"


# ==============================================================================
# The canonical-UTC guard the discard used to provide must not regress
# ==============================================================================

class TestCanonicalUtcIsStillGuaranteed:
    def test_storedValueIsAlwaysCanonicalIso(self) -> None:
        """
        Given: readings in several shapes
        When:  they are written
        Then:  every stored timestamp matches the canonical format

        doNoHarm names this explicitly: UTC canonicality is exactly what the
        old discard protected, and converting must preserve it rather than
        trade one correctness property for another.
        """
        import re

        from src.common.time.helper import CANONICAL_ISO_REGEX

        for ts in (_CAPTURED_LOCAL, datetime(2026, 1, 15, 12, 0, 0),
                   datetime(2026, 9, 23, 18, 0, 0, tzinfo=UTC)):
            db = _FakeDatabase()
            helperLogReading(db, _reading(ts), config=_cfg(_RATIFIED_ZONE))
            assert re.match(CANONICAL_ISO_REGEX, _storedTimestamp(db))
