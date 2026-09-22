################################################################################
# File Name: test_sync_reconcile.py
# Purpose/Description: ARCH-047 -- pin the Pi->server reconciliation comparison
#                      logic. Both traps that made my first live run report
#                      1,190 phantom mismatches are pinned here, because both
#                      would otherwise report CORRECT data as data loss.
# Author: Atlas (ARCH-047, at CIO direction 2026-09-22)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Tests for the sync reconciliation comparator (ARCH-047)."""

from __future__ import annotations

import pytest

from tools.sync.reconcile import (
    FLOAT_KIND_COLUMNS,
    _normaliseTs,
    compareRow,
    f32,
    summarise,
)


class TestFloat32Narrowing:
    """The server stores `float` kind as MariaDB FLOAT -- 4 bytes, not 8."""

    def test_f32_narrowsAsTheServerStorageDoes(self) -> None:
        assert f32(0.22026655273437498) == 0.22026655077934265

    def test_theNarrowedValueIsWhatTheServerACTUALLYHELD(self) -> None:
        """MEASURED 2026-09-22, edr_imu_sample source_id 58491390.

        Pi float64 0.22026655273437498 -> server CAST(... AS DECIMAL(40,30))
        read back 0.220266550779342650. Difference from f32(pi): exactly 0.

        Scale 30, not 18: DECIMAL(30,18) still truncated a small float at 4e-19.
        """
        assert f32(0.22026655273437498) == pytest.approx(0.220266550779342650, abs=0.0)

    def test_strictEqualityWouldFail_whichIsTheWholePoint(self) -> None:
        """🔴 A naive `pi == server` reports data loss where there is none."""
        pi = 0.22026655273437498
        assert pi != f32(pi)

    def test_none_staysNone(self) -> None:
        assert f32(None) is None


class TestCompareRow:
    def _pi(self, **kw):
        base = {"seq": 1, "accel_x": 0.22026655273437498, "drive_id": None,
                "data_source": "real", "ts_capture": 1234.5}
        base.update(kw)
        return base

    def test_narrowedFloat_MATCHES_whenComparedThroughF32(self) -> None:
        srv = {"seq": "1", "accel_x": "0.220266550779342650", "drive_id": "NULL",
               "data_source": "real", "ts_capture": "1234.5"}
        assert compareRow(self._pi(), srv) == []

    def test_genuineValueChange_IS_reported(self) -> None:
        """The comparator must still catch real corruption -- it is not a rubber stamp."""
        srv = {"seq": "1", "accel_x": "0.300000000000000000", "drive_id": "NULL",
               "data_source": "real", "ts_capture": "1234.5"}
        bad = compareRow(self._pi(), srv)
        assert [b[0] for b in bad] == ["accel_x"]

    def test_tsCapture_isNOTnarrowed_itIsDOUBLEOnTheServer(self) -> None:
        """monotonic_s -> DOUBLE. The JOIN KEY must survive intact or the whole
        raw<->derived pairing is built on a rounded value."""
        assert "ts_capture" not in FLOAT_KIND_COLUMNS
        pi = self._pi(ts_capture=1758542401.123456789)
        srv = {"seq": "1", "accel_x": "0.220266550779342650", "drive_id": "NULL",
               "data_source": "real", "ts_capture": "1758542401.123456789"}
        assert compareRow(pi, srv) == []

    def test_nullOnBothSides_matches(self) -> None:
        srv = {"seq": "1", "accel_x": "NULL", "drive_id": "NULL",
               "data_source": "real", "ts_capture": "1234.5"}
        assert compareRow(self._pi(accel_x=None), srv) == []

    def test_nullOnOneSideOnly_isAMismatch(self) -> None:
        """A NULL that became a value, or a value that became NULL, is real loss."""
        srv = {"seq": "1", "accel_x": "0.5", "drive_id": "NULL",
               "data_source": "real", "ts_capture": "1234.5"}
        assert [b[0] for b in compareRow(self._pi(accel_x=None), srv)] == ["accel_x"]


class TestSummariseVerdict:
    def test_missingRows_failsEvenWhenEveryComparedValueMatched(self) -> None:
        """🔴 A value check over the rows that ARRIVED cannot see the rows that
        did not. Counting first is not ceremony."""
        s = summarise(piCount=111, serverCount=110, missingIds=[42], mismatches=[])
        assert s["pass"] is False
        assert "MISSING" in s["verdict"]

    def test_allPresentAndAllMatch_passes(self) -> None:
        s = summarise(piCount=111, serverCount=111, missingIds=[], mismatches=[])
        assert s["pass"] is True

    def test_valueMismatch_fails(self) -> None:
        s = summarise(piCount=111, serverCount=111, missingIds=[],
                      mismatches=[(1, "accel_x", 0.1, "0.2")])
        assert s["pass"] is False
        assert "VALUE" in s["verdict"]

    def test_zeroRowsInRange_isNOTapass(self) -> None:
        """🔴 An empty comparison must never read as success. 0 == 0 is the
        shape of a check that ran against nothing."""
        s = summarise(piCount=0, serverCount=0, missingIds=[], mismatches=[])
        assert s["pass"] is False
        assert "NO ROWS" in s["verdict"]


class TestTimestampRendering:
    """Pi stores ISO TEXT; the server stores DATETIME. Same instant, two renders."""

    def test_isoAndSqlRenderingsOfTheSameInstant_match(self) -> None:
        assert _normaliseTs("2026-09-21T19:05:35Z") == _normaliseTs("2026-09-21 19:05:35")

    def test_aGenuinelyDifferentInstant_stillMismatches(self) -> None:
        """🔴 Normalising must not blind the check to a real timestamp change."""
        assert _normaliseTs("2026-09-21T19:05:35Z") != _normaliseTs("2026-09-21 19:05:36")

    def test_comparingTheRAWstrings_wouldFlagEveryRow(self) -> None:
        """The failure this exists to prevent: a format difference reading as
        total data loss on every single row."""
        assert "2026-09-21T19:05:35Z" != "2026-09-21 19:05:35"
