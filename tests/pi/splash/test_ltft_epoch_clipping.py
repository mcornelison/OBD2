################################################################################
# File Name: test_ltft_epoch_clipping.py
# Purpose/Description: F-096 / ARCH-047 -- the LTFT epoch must be bounded by the
#                      RESET BOUNDARY, not by a drive count, and the two
#                      "no reset found" cases must be distinguishable.
# Author: Atlas (ARCH-047)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""F-096: a clipped epoch must announce itself, not pose as a whole one."""

from __future__ import annotations

from pi.splash.ltft_trend_emitter import _currentEpoch


def _rec(driveId: int, isReset: bool = False) -> dict:
    return {"driveId": driveId, "isReset": isReset, "ltftMean": 1.0,
            "qualifyingCount": 30, "ts": "2026-09-22T00:00:00Z"}


class TestEpochBoundary:
    """`epochBreak=False` used to mean EITHER 'no reset exists' OR 'I did not
    look far enough'. The function returned the identical value for both, so a
    window that straddled a reset was indistinguishable from a whole epoch."""

    def test_resetInWindow_epochStartsAfterIt(self) -> None:
        recs = [_rec(10), _rec(11, isReset=True), _rec(12), _rec(13)]
        epoch, epochBreak, start, clipped = _currentEpoch(recs, historyExhausted=True)
        assert [r["driveId"] for r in epoch] == [12, 13]
        assert epochBreak is True
        assert start == 12
        assert clipped is False

    def test_noReset_andHistoryEXHAUSTED_isAWholeValidEpoch(self) -> None:
        """Genuinely no reset in all of recorded history -- the window IS the epoch."""
        recs = [_rec(1), _rec(2), _rec(3)]
        epoch, epochBreak, start, clipped = _currentEpoch(recs, historyExhausted=True)
        assert len(epoch) == 3
        assert epochBreak is False
        assert start == 1
        assert clipped is False

    def test_noReset_andHistoryNOTexhausted_isCLIPPED_andSaysSo(self) -> None:
        """🔴 THE F-096 DEFECT.

        The reader hit its limit without finding a reset, so the epoch may
        extend further back. Reporting the oldest FETCHED drive as the epoch
        start is a guess wearing a fact's clothes -- and the baseline computed
        from it may straddle a boundary the spec forbids crossing.
        """
        recs = [_rec(64), _rec(65), _rec(66)]
        epoch, epochBreak, start, clipped = _currentEpoch(recs, historyExhausted=False)
        assert clipped is True
        assert start is None, (
            "a clipped epoch has no KNOWN start -- returning the oldest fetched "
            "drive is exactly the defect: today it reports 64 where the real "
            "epoch starts at 37"
        )

    def test_clipped_isDistinguishableFromWholeEpoch_theWHOLEPOINT(self) -> None:
        """Both have epochBreak False. Only `clipped` separates them."""
        whole = _currentEpoch([_rec(1), _rec(2)], historyExhausted=True)
        cut = _currentEpoch([_rec(1), _rec(2)], historyExhausted=False)
        assert whole[1] == cut[1] is False          # epochBreak cannot tell them apart
        assert whole[3] != cut[3]                   # `clipped` can

    def test_resetFound_isNeverClipped_evenIfHistoryContinues(self) -> None:
        """Once the boundary is IN the window, nothing older can matter."""
        recs = [_rec(10), _rec(11, isReset=True), _rec(12)]
        _epoch, epochBreak, start, clipped = _currentEpoch(recs, historyExhausted=False)
        assert epochBreak is True
        assert start == 12
        assert clipped is False

    def test_emptyRecords_isNotAnEpoch(self) -> None:
        epoch, epochBreak, start, clipped = _currentEpoch([], historyExhausted=True)
        assert epoch == []
        assert start is None
        assert epochBreak is False
        assert clipped is False

    def test_theResetDriveItselfBelongsToNeitherSide(self) -> None:
        recs = [_rec(1), _rec(2, isReset=True), _rec(3)]
        epoch, _b, _s, _c = _currentEpoch(recs, historyExhausted=True)
        assert [r["driveId"] for r in epoch] == [3]

    def test_raisingTheDriveCountWouldNOTfixIt(self) -> None:
        """🔴 Why the fix is a BOUNDARY, not a bigger number.

        A longer window still reports clipped when the epoch outruns it. That is
        the point: 20 -> 50 just moves the defect to the next 51-drive epoch.
        """
        long = [_rec(i) for i in range(100)]
        _e, _b, start, clipped = _currentEpoch(long, historyExhausted=False)
        assert clipped is True
        assert start is None
