"""ARCH-027: the accelerometer-trust diagnostic on PitchFusion.

WHY IT EXISTS. The filter already decides, every update, whether the
accelerometer is close enough to 1 g to be treated as gravity. When it is not,
the correction is skipped and pitch runs on gyro integration alone -- which
drifts. Until now that decision was invisible: a consumer could not tell whether
a grade reading came from fused data or from an unaided gyro.

`imufusion` exposes exactly this as `accelerometer_ignored`, and it measured
3-5% on drive 77. It is the one thing the library had that we did not, and the
2026-09-16 comparison recommended copying it rather than adopting the library.

🔴 IT RECORDS THE EXISTING DECISION, it does not recompute it. A second copy of
"is the accelerometer trusted" could disagree with the first, and then the
diagnostic would describe a filter we are not running.
"""

from __future__ import annotations

import pytest

from pi.sensors.pitch_fusion import STANDARD_GRAVITY_MS2, PitchFusion

LEVEL_1G = (0.0, 0.0, STANDARD_GRAVITY_MS2)
# |a| = 1.05 g: outside the 0.02 band, so the accelerometer is ignored.
HARD_BRAKING = (0.0, 0.0, STANDARD_GRAVITY_MS2 * 1.05)
NO_ROTATION = (0.0, 0.0, 0.0)


def _feed(fusion: PitchFusion, vectors, startAt: float = 100.0, step: float = 0.05) -> None:
    for index, vector in enumerate(vectors):
        fusion.update(vector, NO_ROTATION, startAt + index * step)


class TestAccelIgnoredFlag:
    def test_freshFilterHasNotIgnoredAnything(self) -> None:
        assert PitchFusion().accelIgnored is False

    def test_trustedReadingIsNotIgnored(self) -> None:
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G] * 5)
        assert fusion.accelIgnored is False

    def test_untrustedReadingIsIgnored(self) -> None:
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G, LEVEL_1G, HARD_BRAKING])
        assert fusion.accelIgnored is True

    def test_flagClearsWhenTrustReturns(self) -> None:
        """It reports the LAST update, so recovery must show immediately."""
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G, LEVEL_1G, HARD_BRAKING, LEVEL_1G])
        assert fusion.accelIgnored is False


class TestAccelIgnoredFraction:
    def test_freshFilterReportsZero(self) -> None:
        assert PitchFusion().accelIgnoredFraction == 0.0

    def test_allTrustedIsZero(self) -> None:
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G] * 20)
        assert fusion.accelIgnoredFraction == pytest.approx(0.0)

    def test_allUntrustedIsOne(self) -> None:
        fusion = PitchFusion()
        _feed(fusion, [HARD_BRAKING] * 20)
        assert fusion.accelIgnoredFraction == pytest.approx(1.0)

    def test_halfAndHalf(self) -> None:
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G, HARD_BRAKING] * 10)
        assert fusion.accelIgnoredFraction == pytest.approx(0.5, abs=0.06)

    def test_windowIsRollingSoOldTroubleAgesOut(self) -> None:
        """A consumer needs 'is grade trustworthy NOW', not a lifetime average."""
        fusion = PitchFusion(accelTrustWindow=10)
        _feed(fusion, [HARD_BRAKING] * 10)
        assert fusion.accelIgnoredFraction == pytest.approx(1.0)
        _feed(fusion, [LEVEL_1G] * 10, startAt=200.0)
        assert fusion.accelIgnoredFraction == pytest.approx(0.0)


class TestReseedPathCounts:
    """🔴 The re-seed branch returns BEFORE any correction is applied.

    Those updates must count as 'no accel correction applied'. Skipping them
    would make the fraction look healthiest exactly when the filter is being
    repeatedly re-seeded across gaps -- i.e. when it is struggling most.
    """

    def test_untrustedReseedCountsAsIgnored(self) -> None:
        fusion = PitchFusion()
        fusion.update(HARD_BRAKING, NO_ROTATION, 100.0)
        assert fusion.accelIgnored is True
        assert fusion.accelIgnoredFraction == pytest.approx(1.0)

    def test_trustedReseedCountsAsApplied(self) -> None:
        fusion = PitchFusion()
        fusion.update(LEVEL_1G, NO_ROTATION, 100.0)
        assert fusion.accelIgnored is False
        assert fusion.accelIgnoredFraction == pytest.approx(0.0)

    def test_gapReseedIsCounted(self) -> None:
        """A gap longer than tau forces a re-seed; it is still an update."""
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G] * 5)
        fusion.update(HARD_BRAKING, NO_ROTATION, 1000.0)
        assert fusion.accelIgnored is True


class TestMalformedInputIsNotAVerdict:
    def test_nonFiniteVectorDoesNotChangeTheDiagnostic(self) -> None:
        """A malformed burst is ignored outright by update(). It is not evidence
        that the accelerometer was distrusted -- nothing was judged at all."""
        fusion = PitchFusion()
        _feed(fusion, [LEVEL_1G] * 10)
        before = fusion.accelIgnoredFraction
        fusion.update((float("nan"), 0.0, 0.0), NO_ROTATION, 200.0)
        assert fusion.accelIgnoredFraction == pytest.approx(before)
        assert fusion.accelIgnored is False


class TestResetClearsTheDiagnostic:
    def test_resetClearsFlagAndWindow(self) -> None:
        """reset() drops the attitude, so the diagnostic describing it must go too.

        Unlike the ZUPT bias, which survives on purpose (it is a property of how
        the board is bolted in), the trust history belongs to the discarded
        estimate.
        """
        fusion = PitchFusion()
        _feed(fusion, [HARD_BRAKING] * 10)
        assert fusion.accelIgnoredFraction == pytest.approx(1.0)

        fusion.reset()

        assert fusion.accelIgnored is False
        assert fusion.accelIgnoredFraction == 0.0


class TestMatchesTheRealTrustRule:
    """The diagnostic must track the SAME band the filter corrects on."""

    def test_readingJustInsideTheBandIsTrusted(self) -> None:
        fusion = PitchFusion(accelTrustBand=0.02)
        _feed(fusion, [(0.0, 0.0, STANDARD_GRAVITY_MS2 * 1.019)] * 5)
        assert fusion.accelIgnored is False

    def test_readingJustOutsideTheBandIsIgnored(self) -> None:
        fusion = PitchFusion(accelTrustBand=0.02)
        _feed(fusion, [(0.0, 0.0, STANDARD_GRAVITY_MS2 * 1.021)] * 5)
        assert fusion.accelIgnored is True

    def test_ourMeasuredRestReadingSitsInsideByAHair(self) -> None:
        """Measured 1.0184 g at rest -- inside a 0.02 band by 0.0016.

        Pins the margin that makes the accelerometer scale calibration worth
        doing: a slightly worse sensor falls outside and the correction stops.
        """
        fusion = PitchFusion(accelTrustBand=0.02)
        _feed(fusion, [(0.0, 0.0, STANDARD_GRAVITY_MS2 * 1.0184)] * 5)
        assert fusion.accelIgnored is False
