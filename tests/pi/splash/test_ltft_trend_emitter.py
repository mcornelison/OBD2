################################################################################
# File Name: test_ltft_trend_emitter.py
# Purpose/Description: RECORDS THE SUPERSESSION of the US-420 `ltft-trend`
#   contract by Spool's TUNER-005 contract (US-661).
#
#   This file used to hold 19 tests pinning the US-420 semantics: an ABSOLUTE
#   drift classifier (|LTFT| <= 5 ok, <= 10 amber, beyond down) scored from
#   ZERO, a 2-drive minimum, an UNGATED per-drive mean, and a headline taken
#   from the NEWEST drive. Every one of those was grounded in offices/tuner/
#   cards/safe-range-fuel-trims.md, which specs/grounded-knowledge.md
#   "LTFT trend contract (US-661)" (Spool, 2026-08-31, measured over 17,634 LTFT
#   samples across 56 drives) SUPERSEDES for this car.
#
#   THE TESTS ARE NOT DELETED SILENTLY, AND THAT IS THE POINT OF THIS FILE. A
#   reader diffing US-420 against the tree would otherwise find a classifier
#   they can no longer see the reasoning for and file a defect against correct
#   code -- the failure mode US-645 and US-672 both had to write a test to
#   prevent. What replaced each assertion, and why, is recorded below; the
#   replacement behaviour itself is proven in
#   test_ltft_trend_spool_contract.py, which is where the live contract lives.
#
#   The two US-420 invariants that SURVIVED unchanged -- real-drives-only, and
#   the never-raise best-effort write -- are re-asserted there rather than here,
#   so there is one home per behaviour.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Ralph (Rex)  | Initial implementation (US-420 LTFT trend card).
# 2026-09-04    | Ralph (Rex)  | US-661 -- replaced with the supersession record;
#               |              | the live contract moved to
#               |              | test_ltft_trend_spool_contract.py.
# 2026-10-14    | Ralph (Rex)  | US-881-a -- points[].inMedian cases appended.
# ================================================================================
################################################################################

"""US-661: records that the US-420 `ltft-trend` contract was superseded."""

from __future__ import annotations

import pi.splash.ltft_trend_emitter as emitter

# The US-420 public names, each with the measurement that retired it. Kept as
# DATA rather than prose so the assertion below is executable: if anyone
# re-introduces one of these, this test names it and the reason it went.
_RETIRED_SYMBOLS = {
    "classifyLtftDrift": (
        "scored |LTFT| as an ABSOLUTE distance from zero. Spool's band is "
        "'+/-4 pp of the CURRENT EPOCH's baseline' -- the prior ECU's grand "
        "mean was -2.311 % and the current one's is +0.009 %, so scoring from "
        "zero spends most of an epoch's noise budget on a difference that is "
        "not a fault. Replaced by the epoch-relative verdict in "
        "buildLtftTrendState."
    ),
    "LTFT_OK_ABS": (
        "the +/-5 % 'normal' band. Below the measured between-drive noise floor "
        "(drive means spread up to 3.72 pp on the SAME DAY on a healthy "
        "engine), so it would have fired on healthy data. Replaced by "
        "LTFT_NOISE_FLOOR_PP = 4.0 measured against the EPOCH BASELINE."
    ),
    "LTFT_DRIFT_ABS": (
        "renamed to LTFT_FAULT_ABS and re-documented as a CONVENTION that has "
        "NEVER fired on this car and is untested here -- retained only because "
        "the faults it names move LTFT by 10-25 pp, not 3."
    ),
    "MIN_DRIVES_FOR_TREND": (
        "a 2-drive minimum. At an SD of 1.43 pp between drives, two drives "
        "resolve to nothing. Replaced by TREND_MEDIAN_WINDOW = 5, which "
        "resolves to roughly +/-0.6 pp."
    ),
    "readLtftTrend": (
        "aggregated an UNGATED mean of every LTFT row in a drive. Spool's gate "
        "(coolant >= 85 C AND closed loop AND >= 20 qualifying samples) is the "
        "whole substance of the card; an ungated mean is the 'naive "
        "implementation' the contract opens by forbidding. Replaced by "
        "readLtftDriveRows + qualifyingSamples + buildDriveRecords."
    ),
    "TREND_EPSILON_PCT_ABSOLUTE": (
        "never existed under this name; listed to prove the sweep reports "
        "absent symbols as absent rather than passing vacuously."
    ),
}


def test_theUs420AbsoluteContractIsGone_andWhyIsRecorded():
    """
    Given: the US-420 public API, whose bands were grounded in a tuner note that
        Spool's measured TUNER-005 contract superseded
    When: the module is inspected
    Then: none of those names is still exported.

    THE REASON EACH ONE WENT IS IN `_RETIRED_SYMBOLS`, deliberately beside the
    assertion. A permanently absent symbol with no recorded reason is how a
    later reader "restores" a classifier that measurement retired.
    """
    resurrected = [name for name in _RETIRED_SYMBOLS if hasattr(emitter, name)]

    assert resurrected == [], (
        "US-420 symbols are back without re-opening the measurement that "
        f"retired them: {resurrected}"
    )


def test_theSupersedingContractIsTheOneInTheTree():
    """
    Given: the replacement constants
    When: they are read
    Then: they carry Spool's MEASURED values, not the retired US-420 ones.

    Pinned as a pair -- the old value gone AND the new value present -- because
    "the old constant is absent" is also satisfied by a module that defines
    nothing at all.
    """
    assert emitter.TREND_MEDIAN_WINDOW == 5
    assert emitter.LTFT_NOISE_FLOOR_PP == 4.0
    assert emitter.LTFT_FAULT_ABS == 10.0
    assert emitter.GATE_COOLANT_MIN_C == 85.0
    assert emitter.GATE_MIN_QUALIFYING_SAMPLES == 20


def test_theProducerSeamIsStillTheOneTheCardConsumes():
    """
    Given: the rebuilt module
    When: its SSOT slot + PID are read
    Then: they are unchanged from US-420.

    The CONTRACT changed; the SEAM did not. `ltft-trend` is still the file the
    carousel Fuel Trim card polls and bank-1 LTFT is still the signal, so this
    was a semantics change and not a re-plumbing.
    """
    assert emitter.LTFT_TREND_FILENAME == "ltft-trend"
    assert emitter.LTFT_PID == "LONG_FUEL_TRIM_1"


# ===========================================================================
# US-881-a -- every published point says whether the headline median used it.
# ===========================================================================

_NOW = "2026-10-14T12:00:00Z"


def _records(means: list[float | None], *, firstDriveId: int = 101) -> list[dict]:
    """Per-drive records as buildDriveRecords returns them, oldest first, no reset."""
    return [
        {
            "driveId": firstDriveId + index,
            "ts": f"2026-10-{1 + index:02d}T16:40:00Z",
            "sampleCount": 300,
            "qualifyingCount": 0 if mean is None else 250,
            "ltftMean": mean,
            "stftMean": None if mean is None else 0.5,
            "isReset": False,
        }
        for index, mean in enumerate(means)
    ]


def _inMedianById(state: dict) -> dict[int, bool]:
    return {point["driveId"]: point["inMedian"] for point in state["points"]}


def test_inMedian_eightDrivesWindowFive_newestFiveTrue_otherThreeFalse():
    """
    Given: an epoch of 8 drives, each with an ltftMean, medianWindow 5
    When: the state is built
    Then: the newest 5 points are inMedian true and the other 3 false.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]),
        nowIso=_NOW,
        medianWindow=5,
    )

    assert state["median"] is not None
    assert [p["inMedian"] for p in state["points"]] == [False] * 3 + [True] * 5
    assert all(type(p["inMedian"]) is bool for p in state["points"])


def test_inMedian_insufficientHistory_everyPointFalse():
    """
    Given: an epoch of only 3 drives (fewer than medianWindow 5)
    When: the state is built
    Then: no median is published and every point is inMedian false.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0, 2.0, 3.0]), nowIso=_NOW, medianWindow=5
    )

    assert state["median"] is None
    assert state["reason"] == emitter.REASON_INSUFFICIENT_HISTORY
    assert len(state["points"]) == 3
    assert [p["inMedian"] for p in state["points"]] == [False, False, False]


def test_inMedian_epochClipped_noMedian_everyPointFalse():
    """
    Given: 8 drives whose history a LIMIT may have cut short (epochClipped)
    When: the state is built
    Then: no median is published, so every point is inMedian false.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0] * 8), nowIso=_NOW, historyExhausted=False
    )

    assert state["median"] is None
    assert state["points"]
    assert all(p["inMedian"] is False for p in state["points"])


def test_inMedian_pointsCutToDisplayWindow_matchedByDriveIdNotPosition():
    """
    Given: 8 drives, medianWindow 5, but only the newest 6 published (displayPoints 6)
    When: the state is built
    Then: the median drives (104..108) are true and 103 false -- matched by driveId,
        not by the position in the cut list.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0] * 8), nowIso=_NOW, medianWindow=5, displayPoints=6
    )

    assert _inMedianById(state) == {
        103: False,
        104: True,
        105: True,
        106: True,
        107: True,
        108: True,
    }


def test_inMedian_displayWindowNarrowerThanMedian_everyPublishedPointTrue():
    """
    Given: 8 drives, medianWindow 5, displayPoints 3
    When: the state is built
    Then: all 3 published points (106..108) were used by the median, so all true.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0] * 8), nowIso=_NOW, medianWindow=5, displayPoints=3
    )

    assert _inMedianById(state) == {106: True, 107: True, 108: True}


def test_inMedian_driveWithoutQualifyingMean_isNoPoint_medianSetIsLastFivePoints():
    """
    Given: 7 drives where drive 106 never cleared the gate (no point)
    When: the state is built
    Then: the median set is the newest 5 POINTS -- 102, 103, 104, 105, 107 --
        exactly the values rollingMedian took.
    """
    state = emitter.buildLtftTrendState(
        driveRecords=_records([1.0, 2.0, 3.0, 4.0, 5.0, None, 7.0]), nowIso=_NOW
    )

    assert _inMedianById(state) == {
        101: False,
        102: True,
        103: True,
        104: True,
        105: True,
        107: True,
    }
    assert state["median"] == 4.0


def test_inMedian_currentAndEveryOtherFieldUnchanged():
    """
    Given: a sufficient epoch
    When: the state is built
    Then: `current` keeps its four keys (inMedian is a points-only key) and the
        other point keys are unchanged.
    """
    state = emitter.buildLtftTrendState(driveRecords=_records([1.0] * 6), nowIso=_NOW)

    assert set(state["current"]) == {"driveId", "ts", "ltftAvg", "sampleCount"}
    assert set(state["points"][0]) == {"driveId", "ts", "ltftAvg", "sampleCount", "inMedian"}
