################################################################################
# File Name: test_ltft_trend_spool_contract.py
# Purpose/Description: US-661 -- the `ltft-trend` producer measured against
#   SPOOL'S TUNER-005 CONTRACT (specs/grounded-knowledge.md "LTFT trend contract
#   (US-661)"), which is the hard gate the story names. The pre-existing US-420
#   emitter was built against the SUPERSEDED offices/tuner/cards/
#   safe-range-fuel-trims.md bands (absolute +/-5 ok, +/-10 danger) and had NO
#   sample gate, NO 5-drive median and NO epoch boundary -- i.e. it was exactly
#   the "naive implementation" Spool's contract opens by forbidding:
#
#       "A naive implementation (mean LTFT per drive, plot the points, join
#        them) draws a chart that wanders up to 3.72 pp between drives on the
#        same day with nothing wrong. Anyone reading that for drift finds
#        drift, every time."
#
#   THE LOAD-BEARING TEST IN THIS FILE IS THE AS-OF ALIGNMENT ONE. Spool's gate
#   is per-SAMPLE (coolant >= 85 AND fuel-system-status == 2), but realtime_data
#   is long/narrow and `logger.py` stamps `utcIsoNow()` PER READING inside the
#   per-reading loop -- so every parameter in one poll cycle lands on its OWN
#   timestamp. An exact-timestamp join therefore matches ~0 rows in production,
#   the gate never passes, and the card reads WARMING forever. It would still be
#   green in any fixture whose rows share a timestamp -- which is what the
#   US-420 fixture (`_seedDrive`, all rows on the schema DEFAULT timestamp) did.
#   Every fixture here uses DISTINCT, round-robin-ordered timestamps so the
#   alignment is actually exercised.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-04    | Ralph (Rex)  | Initial -- US-661 Spool TUNER-005 contract.
# ================================================================================
################################################################################

"""US-661: `ltft-trend` measured against Spool's TUNER-005 contract."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

from pi.splash.ltft_trend_emitter import (
    COOLANT_PID,
    FUEL_SYSTEM_CLOSED_LOOP,
    FUEL_SYSTEM_PID,
    GATE_COOLANT_MIN_C,
    GATE_HOLD_MAX_SECONDS,
    GATE_MIN_QUALIFYING_SAMPLES,
    LEVEL_AMBER,
    LEVEL_DOWN,
    LEVEL_INSUFFICIENT,
    LEVEL_OK,
    LTFT_PID,
    LTFT_TREND_FILENAME,
    REASON_INSUFFICIENT_HISTORY,
    REASON_WARMING,
    STFT_PID,
    TREND_MEDIAN_WINDOW,
    buildDriveRecords,
    buildLtftTrendState,
    isAdaptiveResetDrive,
    makeLtftTrendEmitter,
    qualifyingLtftSamples,
    readLtftDriveRows,
    rollingMedian,
)

_NOW = "2026-09-04T12:00:00Z"
_T0 = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)


def _iso(offsetSeconds: float) -> str:
    """An ISO-8601 second-resolution UTC stamp `offsetSeconds` after the epoch."""
    return (_T0 + timedelta(seconds=offsetSeconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# `utcIsoNow()` is SECOND-resolution (src/common/time/helper.py), so the skew
# between parameters in one poll cycle is whole seconds -- a Bluetooth
# round-robin spends ~100-300 ms per PID and a full cycle spans several seconds.
# That is what makes an exact-timestamp join so treacherous: it does not fail
# cleanly, it matches SOMETIMES depending on where the second boundary lands.
_PARAM_SKEW_S = (0, 1, 2, 3)


# ---------------------------------------------------------------------------
# Fixture builders.
#
# `_pollCycle` reproduces the REAL producer's row shape: one poll cycle emits
# the three parameters on three DIFFERENT timestamps, because logger.py stamps
# utcIsoNow() per reading. Anything that only passes when the three share a
# timestamp is testing a fixture, not the Pi.
# ---------------------------------------------------------------------------


def _pollCycle(
    cycleIndex: int,
    *,
    ltft: float,
    coolant: float,
    fuelStatus: float,
    stft: float | None = None,
    cadenceS: float = 5.0,
) -> list[tuple[str, str, float]]:
    """One round-robin poll cycle -> (timestamp, parameter_name, value) rows.

    The parameters are stamped one second apart, which is what a real Bluetooth
    round-robin produces against a second-resolution clock. At the default 5 s
    cadence, 20 samples span 100 s -- Spool's own "~100 s of qualifying
    operation" for the 20-sample floor, so the fixture's time base is the
    contract's, not an invented one.
    """
    base = cycleIndex * cadenceS
    rows = [
        (_iso(base + _PARAM_SKEW_S[0]), COOLANT_PID, coolant),
        (_iso(base + _PARAM_SKEW_S[1]), FUEL_SYSTEM_PID, fuelStatus),
        (_iso(base + _PARAM_SKEW_S[2]), LTFT_PID, ltft),
    ]
    if stft is not None:
        rows.append((_iso(base + _PARAM_SKEW_S[3]), STFT_PID, stft))
    return rows


def _warmDriveRows(
    ltftValues: list[float],
    *,
    coolant: float = 90.0,
    fuelStatus: float = FUEL_SYSTEM_CLOSED_LOOP,
    stft: float | None = None,
    startCycle: int = 0,
) -> list[tuple[str, str, float]]:
    """A fully-qualifying warm closed-loop drive of `len(ltftValues)` samples."""
    rows: list[tuple[str, str, float]] = []
    for i, value in enumerate(ltftValues):
        rows.extend(
            _pollCycle(
                startCycle + i,
                ltft=value,
                coolant=coolant,
                fuelStatus=fuelStatus,
                stft=stft,
            )
        )
    return rows


def _qualifyingDrive(mean: float, *, samples: int = 25) -> list[tuple[str, str, float]]:
    """A drive whose qualifying LTFT samples average exactly `mean`."""
    return _warmDriveRows([mean] * samples)


# ===========================================================================
# 1. THE GATE -- all three ANDed, per-sample, as-of aligned.
# ===========================================================================


def test_qualifyingLtftSamples_alignsCoolantAsOf_notByExactTimestamp():
    """
    Given: a real round-robin poll cycle -- coolant, loop status and LTFT each
        land on their OWN timestamp (0.0 s / 0.3 s / 0.6 s apart), exactly as
        logger.py writes them
    When: the gate is evaluated
    Then: the samples QUALIFY.

    THIS IS THE REGRESSION TEST FOR THE WHOLE STORY. An implementation that
    joins coolant/status to LTFT on equal timestamps matches nothing in
    production and the card reads WARMING forever -- while staying green on any
    fixture whose rows share a timestamp. No row here shares a timestamp.
    """
    rows = _warmDriveRows([-1.0] * 20)
    stamps = {ts for ts, _name, _v in rows}
    # Guard the guard: if the fixture ever collapses onto one timestamp this
    # test silently stops testing the thing it exists for.
    assert len(stamps) == len(rows), "fixture must not share timestamps"

    qualifying = qualifyingLtftSamples(rows)

    assert len(qualifying) == 20


def test_qualifyingLtftSamples_coldCoolant_isNotEligible():
    """
    Given: a closed-loop drive whose coolant never reaches 85 C
    When: the gate is evaluated
    Then: no sample qualifies -- coolant is the load-bearing condition.
    """
    rows = _warmDriveRows([-1.0] * 30, coolant=60.0)

    assert qualifyingLtftSamples(rows) == []


def test_qualifyingLtftSamples_coolantBoundaryIsInclusive():
    """
    Given: coolant exactly at the 85 C threshold
    When: the gate is evaluated
    Then: the sample qualifies (>= 85, per the contract's own operator).
    """
    assert len(qualifyingLtftSamples(_warmDriveRows([-1.0] * 5, coolant=85.0))) == 5
    assert qualifyingLtftSamples(_warmDriveRows([-1.0] * 5, coolant=84.9)) == []


def test_qualifyingLtftSamples_openLoopUnderLoad_isNotEligible():
    """
    Given: fuel-system-status 3 -- open loop under load/decel, a WARM state
        (Spool: mean coolant 89.0 C, mean RPM 2515) with coolant well past 85
    When: the gate is evaluated
    Then: nothing qualifies. Only status == 2 (closed loop) is eligible.

    Status 3 is the trap: it is warm, so a coolant-only gate would admit it, and
    trims under open-loop enrichment are not the closed-loop correction the card
    is reporting.
    """
    rows = _warmDriveRows([-1.0] * 30, coolant=89.0, fuelStatus=3.0)

    assert qualifyingLtftSamples(rows) == []


def test_qualifyingLtftSamples_coldOpenLoop_isNotEligible():
    """
    Given: fuel-system-status 1 (open loop, cold)
    When: the gate is evaluated
    Then: nothing qualifies.
    """
    assert qualifyingLtftSamples(_warmDriveRows([-1.0] * 30, fuelStatus=1.0)) == []


def test_qualifyingLtftSamples_staleGateReading_failsClosed():
    """
    Given: a warm closed-loop reading followed by a long silence, then an LTFT
        sample far beyond the hold window with no fresh coolant/status
    When: the gate is evaluated
    Then: the orphaned sample does NOT qualify.

    Fail CLOSED. Holding a coolant reading indefinitely is the latched-channel
    defect this project has fought repeatedly -- an unknown state must never
    resolve to "warm".
    """
    rows = _warmDriveRows([-1.0] * 3)
    staleAt = 3 * 5.0 + GATE_HOLD_MAX_SECONDS + 60.0
    rows.append((_iso(staleAt), LTFT_PID, -1.0))

    qualifying = qualifyingLtftSamples(rows)

    assert len(qualifying) == 3, "the stale-window sample must not qualify"


def test_qualifyingLtftSamples_ltftBeforeAnyGateReading_isNotEligible():
    """
    Given: an LTFT sample that arrives BEFORE any coolant/status reading exists
    When: the gate is evaluated
    Then: it does not qualify -- absence of evidence is not warmth.
    """
    rows = [(_iso(0.0), LTFT_PID, -1.0)] + _warmDriveRows([-1.0] * 5, startCycle=1)

    assert len(qualifyingLtftSamples(rows)) == 5


def test_qualifyingLtftSamples_gateReappliesWhenLoopStatusDrops():
    """
    Given: a drive that warms into closed loop, drops to open-loop-under-load
        mid-drive, then returns to closed loop
    When: the gate is evaluated
    Then: ONLY the closed-loop samples qualify -- the gate is per-sample, not a
        once-per-drive latch.
    """
    rows = _warmDriveRows([-1.0] * 5, startCycle=0)
    rows += _warmDriveRows([9.9] * 4, fuelStatus=3.0, startCycle=5)
    rows += _warmDriveRows([-1.0] * 6, startCycle=9)

    qualifying = qualifyingLtftSamples(rows)

    assert len(qualifying) == 11
    assert 9.9 not in qualifying, "open-loop enrichment must never enter the mean"


# ===========================================================================
# 2. PER-DRIVE POINT -- >= 20 qualifying samples, qualifying samples ONLY.
# ===========================================================================


def test_buildDriveRecords_belowTwentyQualifying_yieldsNoPoint():
    """
    Given: a drive with 19 qualifying samples
    When: the records are built
    Then: it produces NO trend point -- Spool's floor is 20 (~100 s).
    """
    records = buildDriveRecords({1: (None, _warmDriveRows([-1.0] * 19))})

    assert records[0]["ltftMean"] is None
    assert records[0]["qualifyingCount"] == 19


def test_buildDriveRecords_twentyQualifying_yieldsAPoint():
    """
    Given: a drive with exactly 20 qualifying samples
    When: the records are built
    Then: it produces a point (the boundary is inclusive).
    """
    records = buildDriveRecords({1: (None, _warmDriveRows([-1.0] * 20))})

    assert records[0]["qualifyingCount"] == GATE_MIN_QUALIFYING_SAMPLES
    assert records[0]["ltftMean"] == -1.0


def test_buildDriveRecords_meanUsesQualifyingSamplesOnly():
    """
    Given: a drive with 25 warm closed-loop samples at -1.0 and 25 cold samples
        at +12.0
    When: the drive's point is computed
    Then: the mean is -1.0 -- the cold samples are not merely down-weighted,
        they are absent.

    "Never publish a number that failed the gate."
    """
    rows = _warmDriveRows([-1.0] * 25, startCycle=0)
    rows += _warmDriveRows([12.0] * 25, coolant=40.0, fuelStatus=1.0, startCycle=25)

    records = buildDriveRecords({1: (None, rows)})

    assert records[0]["ltftMean"] == -1.0
    assert records[0]["qualifyingCount"] == 25


# ===========================================================================
# 3. EPOCH BOUNDARIES -- never join a line across one.
# ===========================================================================


def test_isAdaptiveResetDrive_bitIdenticalZero_isAReset():
    """
    Given: a drive whose LTFT is bit-identical to exactly 0.000 throughout
        (Spool: drives 35/36, the flat-battery adaptive reset)
    When: the reset detector runs
    Then: it reports a reset.
    """
    assert isAdaptiveResetDrive([0.0] * 40) is True


def test_isAdaptiveResetDrive_zeroVarianceNonZero_isNotAReset():
    """
    Given: a drive with ZERO VARIANCE at -2.344 (Spool: drive 33, a short drive
        parked in one load cell)
    When: the reset detector runs
    Then: it is NOT a reset.

    THE DETECTOR MUST TEST BIT-IDENTITY TO ZERO, NOT ZERO VARIANCE. Zero
    variance false-positives on exactly this drive; bit-identity needs no tuned
    threshold and cannot false-positive.
    """
    assert isAdaptiveResetDrive([-2.344] * 40) is False


def test_isAdaptiveResetDrive_nearZeroButNotIdentical_isNotAReset():
    """
    Given: a drive hovering near zero but not bit-identical to it
    When: the reset detector runs
    Then: NOT a reset -- no epsilon, no tuned threshold.
    """
    assert isAdaptiveResetDrive([0.0, 0.0, 0.78125, 0.0]) is False


def test_isAdaptiveResetDrive_emptyDrive_isNotAReset():
    """
    Given: a drive with no LTFT samples at all
    When: the reset detector runs
    Then: NOT a reset -- an absence is not a measurement of zero.
    """
    assert isAdaptiveResetDrive([]) is False


def test_buildLtftTrendState_seriesBreaksAtAdaptiveReset():
    """
    Given: five qualifying drives at -2.3 (a PRIOR epoch), then a bit-identical
        0.000 reset drive, then five qualifying drives at +0.1
    When: the state is built
    Then: the published series contains ONLY the post-reset epoch, and the break
        is labelled.

    "Never join a line across an epoch boundary. Break the series and label the
    break." A trend spanning the reset compares two different adaptive states.
    """
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 6):
        perDrive[driveId] = (None, _qualifyingDrive(-2.3))
    perDrive[6] = (None, _warmDriveRows([0.0] * 30))
    for driveId in range(7, 12):
        perDrive[driveId] = (None, _qualifyingDrive(0.1))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["epochBreak"] is True
    assert state["epochStartDriveId"] == 7
    driveIds = [p["driveId"] for p in state["points"]]
    assert driveIds == [7, 8, 9, 10, 11]
    assert all(d > 6 for d in driveIds), "no pre-reset drive may enter the series"


def test_buildLtftTrendState_noReset_keepsTheWholeSeries():
    """
    Given: six qualifying drives with no reset anywhere
    When: the state is built
    Then: all six are in the series and no break is claimed.
    """
    perDrive = {d: (None, _qualifyingDrive(-1.0)) for d in range(1, 7)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["epochBreak"] is False
    assert len(state["points"]) == 6


def test_epochDetection_onlyTheResetDetectorExistsOnThisTier_andWhy():
    """
    Given: the Pi database schema this producer actually reads
    When: it is searched for the ECU-identity columns the contract's SECOND
        epoch detector requires
    Then: they are absent -- so only ONE of the contract's two detectors is
        implementable here, and that is RECORDED rather than papered over.

    THE CONTRACT NAMES TWO BOUNDARY DETECTORS (specs/grounded-knowledge.md,
    "LTFT trend contract (US-661)"):

        | ECU identity change | `(part_number, cal_rom)` changes -- already
        |                     | tracked in `vehicle_info`          | Certain |
        | Adaptive memory reset | LTFT bit-identical to 0.000       | Measured |

    The reset detector is built and tested above. The ECU-identity detector is
    NOT, and the reason is a TIER boundary, not an oversight: ECU identity is a
    SERVER-side concept. `ecu_signature` / `cal_signature` live in the MariaDB
    `ecu` table created by src/server/migrations/versions/v0011_us376_ecu_identity.py
    and are FK'd from the SERVER's `vehicle_info.ecu_id`. The PI's SQLite
    `vehicle_info` (src/pi/obdii/database_schema.py) has neither column, and
    this producer runs on the Pi against that database.

    So the contract's "already tracked in `vehicle_info`" is true of the server
    and false of the Pi. Inventing a Pi-side ECU fingerprint to fill the gap is
    exactly what the story forbids -- it would be a boundary detector nobody
    specified, deciding where a tuning series breaks.

    WHAT IT COSTS, STATED: an ECU swap or reflash performed WITHOUT a battery
    disconnect leaves no adaptive reset, so the series would span a 2.86 pp
    step the contract calls "comparing two engines". The reset detector covers
    the observed history (the 2026-07-31 flat battery), so this is a latent gap
    rather than a live wrong number. Filed as I-us661-ecu-epoch-detector.

    This test FAILS THE DAY THE COLUMNS ARRIVE on the Pi -- which is the correct
    moment to reopen the second detector, with this reasoning attached.
    """
    # Resolved off the imported module rather than by counting `..` from the
    # test file: this reads the schema the Pi ACTUALLY imports, so it cannot
    # drift into asserting against a stale copy at a hand-built path.
    import pi.obdii.database_schema as schemaModule

    with open(schemaModule.__file__, encoding="utf-8") as handle:
        schema = handle.read()

    assert "CREATE TABLE IF NOT EXISTS vehicle_info" in schema, (
        "fixture guard: the Pi vehicle_info table must still exist for this "
        "test to be measuring anything"
    )
    assert "part_number" not in schema
    assert "cal_rom" not in schema

    # And the producer makes no claim it cannot support: nothing in the module
    # reads an ECU identity, so there is no half-wired detector to mistake for
    # a working one.
    import pi.splash.ltft_trend_emitter as emitterModule

    with open(emitterModule.__file__, encoding="utf-8") as handle:
        source = handle.read()
    assert "part_number" not in source
    assert "cal_rom" not in source


# ===========================================================================
# 4. THE HEADLINE IS A 5-DRIVE MEDIAN -- never a single drive.
# ===========================================================================


def test_rollingMedian_isTheMedianNotTheMean():
    """
    Given: a window containing one outlier
    When: the rolling median is taken
    Then: the outlier does not move it (which is the entire point of a median).
    """
    assert rollingMedian([0.0, 0.0, 0.0, 0.0, 20.0], TREND_MEDIAN_WINDOW) == [0.0]


def test_buildLtftTrendState_headlineIsTheMedian_notTheNewestDrive():
    """
    Given: five qualifying drives at -1.0 and a sixth at +3.5 -- a single-drive
        excursion well inside Spool's measured 3.72 pp same-day noise
    When: the state is built
    Then: the headline median stays at -1.0.

    THIS IS THE DEFECT THE STORY EXISTS TO PREVENT. The US-420 builder published
    `current` (the NEWEST drive) as the headline, so this fixture would have
    painted +3.50% -- a number Spool measured as carrying no information at all:
    "a single drive resolves to nothing".
    """
    perDrive = {d: (None, _qualifyingDrive(-1.0)) for d in range(1, 6)}
    perDrive[6] = (None, _qualifyingDrive(3.5))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["median"] == -1.0
    assert state["sufficient"] is True


def test_buildLtftTrendState_fourQualifyingDrives_isInsufficientNotAGuess():
    """
    Given: only four qualifying drives in the epoch -- one short of the window
    When: the state is built
    Then: a typed absence with the insufficient-history reason, NO median, and
        the headline level is never green.
    """
    perDrive = {d: (None, _qualifyingDrive(-1.0)) for d in range(1, 5)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["sufficient"] is False
    assert state["median"] is None
    assert state["level"] == LEVEL_INSUFFICIENT
    assert state["reason"] == REASON_INSUFFICIENT_HISTORY


def test_buildLtftTrendState_shortDrivesDoNotCountTowardTheWindow():
    """
    Given: five drives, but two never accumulate 20 qualifying samples
    When: the state is built
    Then: only three points exist, so the median is withheld.

    Spool measured this as PERMANENT: 5 of 22 drives never qualify. A short
    drive must not be padded into the window to reach five.
    """
    perDrive: dict[int, tuple[str | None, list]] = {
        1: (None, _qualifyingDrive(-1.0)),
        2: (None, _warmDriveRows([-1.0] * 10)),
        3: (None, _qualifyingDrive(-1.0)),
        4: (None, _warmDriveRows([-1.0] * 5)),
        5: (None, _qualifyingDrive(-1.0)),
    }

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert len(state["points"]) == 3
    assert state["median"] is None
    assert state["sufficient"] is False


# ===========================================================================
# 5. THE WARMING STATE -- the correct resting state for ~1 drive in 4.
# ===========================================================================


def test_buildLtftTrendState_gateNeverMet_publishesWarmingAndNoNumber():
    """
    Given: a cold drive that never qualifies
    When: the state is built
    Then: the WARMING typed absence is published and NO trim number appears
        anywhere in the payload.

    "Publish a typed absence with a reason -- never publish a number that failed
    the gate." Asserted at the DIGIT level over the serialised payload, not by
    checking one field: a number that leaked into `current` or `points` would
    satisfy a field-level assertion.
    """
    perDrive = {1: (None, _warmDriveRows([7.77] * 40, coolant=40.0, fuelStatus=1.0))}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["reason"] == REASON_WARMING
    assert state["median"] is None
    assert state["current"] is None
    assert state["points"] == []
    assert state["level"] == LEVEL_INSUFFICIENT
    assert "7.77" not in json.dumps(state)


def test_buildLtftTrendState_noDrivesAtAll_isAnHonestAbsence():
    """
    Given: no drives on record
    When: the state is built
    Then: an honest absence -- never a zero, never a flat line.
    """
    state = buildLtftTrendState(driveRecords=[], nowIso=_NOW)

    assert state["sufficient"] is False
    assert state["median"] is None
    assert state["points"] == []
    assert state["level"] == LEVEL_INSUFFICIENT


# ===========================================================================
# 6. VERDICT -- deviation from the CURRENT EPOCH's baseline, not from zero.
# ===========================================================================


def test_buildLtftTrendState_verdictIsRelativeToEpochBaseline_notToZero():
    """
    Given: an epoch whose drives all sit at -2.31 (Spool's measured PRIOR-ECU
        grand mean) with no drift
    When: the state is built
    Then: the verdict is OK and the deviation is ~0.

    The superseded US-420 classifier scored the ABSOLUTE distance from zero, so
    an epoch legitimately centred away from 0 would burn its whole noise budget
    before the engine did anything. Spool's band is "+/-4 pp of the CURRENT
    EPOCH's baseline".
    """
    perDrive = {d: (None, _qualifyingDrive(-2.31)) for d in range(1, 8)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["baseline"] == -2.31
    assert abs(state["deviationPp"]) < 0.01
    assert state["level"] == LEVEL_OK


def test_buildLtftTrendState_sustainedDeviationBeyondNoiseFloor_isAmber():
    """
    Given: an epoch baselined near 0 whose recent drives have moved out past the
        4.0 pp noise floor
    When: the state is built
    Then: the verdict is AMBER.
    """
    # NOT 0.0 for the baseline drives: bit-identical 0.000 is the ADAPTIVE-RESET
    # sentinel, so seeding "healthy" at exactly zero builds ten reset drives and
    # tests the epoch-break path instead of this one. The real post-reset epoch
    # mean is +0.009 % -- near zero, deliberately not bit-identical to it.
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 11):
        perDrive[driveId] = (None, _qualifyingDrive(0.1))
    for driveId in range(11, 16):
        perDrive[driveId] = (None, _qualifyingDrive(9.0))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["deviationPp"] >= 4.0
    assert state["level"] == LEVEL_AMBER


def test_buildLtftTrendState_anEpochCentredOffZeroIsNotAFault():
    """
    Given: an epoch whose drives ALL sit at -6.0 -- well beyond the 4.0 pp noise
        floor measured from ZERO, but exactly ON its own baseline
    When: the state is built
    Then: the verdict is OK.

    ONE OF THE TWO CASES THAT SEPARATE THE RULES, and neither of the original
    verdict tests did: at -2.31 (Spool's prior-ECU mean) "distance from zero"
    and "distance from the epoch baseline" AGREE, so both were satisfied by the
    wrong rule. Scoring from zero would call this engine faulty for having a
    baseline, which is precisely what the US-420 classifier did.
    """
    perDrive = {d: (None, _qualifyingDrive(-6.0)) for d in range(1, 8)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["baseline"] == -6.0
    assert abs(state["deviationPp"]) < 0.01
    assert state["level"] == LEVEL_OK, "an epoch was called faulty for its baseline"


def test_buildLtftTrendState_aMoveTowardZeroOffAHighBaselineIsStillADeviation():
    """
    Given: an epoch baselined near +8 whose recent drives have moved to +1.0 --
        CLOSE to zero, but far from where this engine normally sits
    When: the state is built
    Then: the verdict is AMBER.

    THE OTHER SEPARATING CASE, and the inverse of the one above. Scored from
    zero, +1.0 % is a healthy-looking number and the card would say nothing
    while the engine's correction moved 7 pp -- a change far outside the 3.72 pp
    same-day noise floor. What matters is the move off the baseline, in EITHER
    direction.
    """
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 11):
        perDrive[driveId] = (None, _qualifyingDrive(8.0))
    for driveId in range(11, 16):
        perDrive[driveId] = (None, _qualifyingDrive(1.0))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["median"] == 1.0
    assert abs(state["deviationPp"]) >= 4.0
    assert state["level"] == LEVEL_AMBER


def test_buildLtftTrendState_beyondConventionalFaultLine_isDown():
    """
    Given: a 5-drive median beyond the conventional +/-10 % fault line
    When: the state is built
    Then: the verdict is DOWN.

    Spool records this line as a CONVENTION that has NEVER fired on this car and
    is untested here; it is retained because the fault it names (vacuum leak,
    failing injector, MAF drift) moves LTFT by 10-25 pp, not 3.
    """
    perDrive = {d: (None, _qualifyingDrive(-14.0)) for d in range(1, 8)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["level"] == LEVEL_DOWN


def test_buildLtftTrendState_insufficientNeverInheritsAGreenVerdict():
    """
    Given: three qualifying drives all comfortably in band
    When: the state is built
    Then: the headline is INSUFFICIENT, not OK.

    A confident green off too little data is the failure this card's whole
    contract is written against.
    """
    # 0.1, not 0.0 -- see the epoch-sentinel note above; three RESET drives
    # would reach the same assertion down a different code path.
    perDrive = {d: (None, _qualifyingDrive(0.1)) for d in range(1, 4)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["level"] == LEVEL_INSUFFICIENT
    assert state["level"] != LEVEL_OK
    assert state["reason"] == REASON_INSUFFICIENT_HISTORY
    assert len(state["points"]) == 3


# ===========================================================================
# 7. TOTAL TRIM -- LTFT + STFT as ONE current value, and STFT is NEVER trended.
# ===========================================================================


def test_buildLtftTrendState_totalTrimIsLtftPlusStft_asOneCurrentValue():
    """
    Given: a qualifying epoch whose most recent drive carries STFT alongside LTFT
    When: the state is built
    Then: `totalTrim` is the sum, as a single current value.

    "Show instead: total trim = LTFT + STFT, as ONE current value, no trend.
    That is what a tuner reads -- the total correction being applied now."
    """
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 6):
        perDrive[driveId] = (None, _warmDriveRows([-1.0] * 25, stft=1.5))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["totalTrim"] == 0.5


def test_buildLtftTrendState_totalTrimNeverMixesTwoDrives():
    """
    Given: an epoch whose most recent drive cleared the gate for STFT but NOT
        for LTFT (19 qualifying LTFT samples against the 20 floor, 25 STFT)
    When: the state is built
    Then: `totalTrim` is None -- it is NEVER the newest drive's STFT added to an
        OLDER drive's LTFT.

    THE TWO PIDS ARE COUNTED SEPARATELY, which is what makes this reachable.
    The gate is per-SAMPLE and applied to each parameter independently, so a
    drive can clear the 20-sample floor for one and miss it for the other --
    the corpus itself is uneven (17,634 LTFT against 17,638 STFT samples), and
    Spool measured 22.7 % of drives producing no LTFT point at all.

    `current` is the newest drive WITH AN LTFT POINT; the newest drive IN THE
    EPOCH may be a later one. Reading STFT from the latter and LTFT from the
    former sums two different drives into a number the contract defines as "the
    total correction being applied NOW" -- a value no drive ever measured.
    Healthy post-reset total trim is -1.37 to +4.05; this fixture would print
    +10.99, above even the 10 pp conventional fault line.

    A UNIFORM FIXTURE CANNOT WITNESS THIS. Every other test in this section
    gives all five drives identical rows, so `current` and the last epoch record
    are the same drive and the two readings agree by construction.

    THE CURRENT DRIVE HERE LOGGED NO STFT AT ALL, so borrowing drive 6's is the
    ONLY way to put a number on the card -- and the honest answer is still the
    typed absence. A producer that reaches for the nearest available reading
    whenever its own is missing is the latched-channel defect
    (specs/ssot-design-pattern.md) wearing a different hat.
    """
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 6):
        perDrive[driveId] = (None, _warmDriveRows([1.0] * 25))

    # Drive 6: a real round-robin that dropped six LTFT responses (a NO DATA /
    # skipped PID) while STFT kept answering. 19 LTFT < 20 <= 25 STFT.
    tailRows = _warmDriveRows([2.0] * 25, stft=9.99)
    ltftSeen = 0
    trimmed: list[tuple[str, str, float]] = []
    for row in tailRows:
        if row[1] == LTFT_PID:
            ltftSeen += 1
            if ltftSeen > 19:
                continue
        trimmed.append(row)
    perDrive[6] = (None, trimmed)

    records = buildDriveRecords(perDrive)

    # Guard the guard: the fixture only tests what it claims while the counts
    # actually straddle the floor in opposite directions.
    tail = records[-1]
    assert tail["driveId"] == 6
    assert tail["ltftMean"] is None, "drive 6 must miss the LTFT floor"
    assert tail["stftMean"] is not None, "drive 6 must clear the STFT floor"

    state = buildLtftTrendState(driveRecords=records, nowIso=_NOW)

    assert state["current"]["driveId"] == 5
    assert state["totalTrim"] is None
    assert state["totalTrim"] != 10.99


def test_buildLtftTrendState_totalTrimIsReadFromTheCurrentDrive_notTheNewest():
    """
    Given: an epoch whose newest LTFT point (drive 5) carries its own STFT, and
        a LATER non-qualifying drive 6 carrying a wildly different STFT
    When: the state is built
    Then: `totalTrim` is drive 5's LTFT + drive 5's STFT.

    THE CONTROL FOR THE TEST ABOVE, and it is load-bearing. "Never mix two
    drives" is also satisfied by never computing a total trim at all, which
    would silently delete the one number Spool says a tuner actually reads.
    This pins that the value is still PRODUCED -- from one drive, coherently.
    """
    perDrive: dict[int, tuple[str | None, list]] = {}
    for driveId in range(1, 5):
        perDrive[driveId] = (None, _warmDriveRows([1.0] * 25, stft=1.0))
    perDrive[5] = (None, _warmDriveRows([-1.0] * 25, stft=1.5))

    tailRows = _warmDriveRows([2.0] * 25, stft=9.99)
    ltftSeen = 0
    trimmed: list[tuple[str, str, float]] = []
    for row in tailRows:
        if row[1] == LTFT_PID:
            ltftSeen += 1
            if ltftSeen > 19:
                continue
        trimmed.append(row)
    perDrive[6] = (None, trimmed)

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    assert state["current"]["driveId"] == 5
    assert state["totalTrim"] == 0.5


def test_buildLtftTrendState_stftIsNeverTrended():
    """
    Given: any built state
    When: its keys are inspected
    Then: there is no STFT series anywhere.

    "Do not trend STFT. It oscillates around its mean by design -- a trend line
    would picture the O2 sensor switching, not the engine."
    """
    perDrive = {d: (None, _warmDriveRows([-1.0] * 25, stft=1.5)) for d in range(1, 6)}

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(perDrive), nowIso=_NOW
    )

    for point in state["points"]:
        assert "stft" not in json.dumps(point).lower()


# ===========================================================================
# 8. THE READER -- real drives only, against a real-shaped table.
# ===========================================================================


def _makeDb() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE drive_summary (
            drive_id INTEGER PRIMARY KEY,
            drive_start_timestamp TEXT NOT NULL
        )
        """
    )
    return conn


def _seedRows(
    conn: sqlite3.Connection,
    driveId: int,
    rows: list[tuple[str, str, float]],
    *,
    dataSource: str = "real",
    addSummary: bool = True,
) -> None:
    if addSummary:
        conn.execute(
            "INSERT OR REPLACE INTO drive_summary (drive_id, drive_start_timestamp) "
            "VALUES (?, ?)",
            (driveId, rows[0][0]),
        )
    for ts, name, value in rows:
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, unit, "
            "data_source, drive_id) VALUES (?, ?, ?, '%', ?, ?)",
            (ts, name, value, dataSource, driveId),
        )
    conn.commit()


def test_readLtftDriveRows_returnsRowsPerDrive_timeOrdered():
    """
    Given: a seeded real drive
    When: the reader runs
    Then: the drive's rows come back in timestamp order, carrying all three
        gate parameters.
    """
    conn = _makeDb()
    _seedRows(conn, 1, _warmDriveRows([-1.0] * 5))

    perDrive = readLtftDriveRows(conn)

    assert set(perDrive) == {1}
    _ts, rows = perDrive[1]
    names = {name for _t, name, _v in rows}
    assert names == {COOLANT_PID, FUEL_SYSTEM_PID, LTFT_PID}
    assert rows == sorted(rows, key=lambda r: r[0])


def test_readLtftDriveRows_excludesNonRealDataSources():
    """
    Given: a simulator drive beside a real one
    When: the reader runs
    Then: only the real drive is returned -- a bench or foreign drive can never
        enter the tune signal.
    """
    conn = _makeDb()
    _seedRows(conn, 1, _warmDriveRows([-1.0] * 5))
    _seedRows(conn, 2, _warmDriveRows([-9.0] * 5), dataSource="physics_sim")
    _seedRows(conn, 3, _warmDriveRows([-8.0] * 5), dataSource="foreign")

    perDrive = readLtftDriveRows(conn)

    assert set(perDrive) == {1}


def test_readLtftDriveRows_endToEnd_producesAQualifyingTrend():
    """
    Given: seven real qualifying drives in a seeded DB
    When: the reader feeds the record builder and the state builder
    Then: a sufficient trend with a 5-drive median is produced.

    The full producer chain over a real-shaped table -- distinct timestamps,
    round-robin parameter order, real data_source filtering.
    """
    conn = _makeDb()
    for driveId in range(1, 8):
        _seedRows(conn, driveId, _qualifyingDrive(-1.0))

    state = buildLtftTrendState(
        driveRecords=buildDriveRecords(readLtftDriveRows(conn)), nowIso=_NOW
    )

    assert state["sufficient"] is True
    assert state["median"] == -1.0
    assert state["level"] == LEVEL_OK


# ===========================================================================
# 9. THE EMITTER -- writes the SSOT, never raises.
# ===========================================================================


def test_emitter_writesTheStateFile(tmp_path):
    """
    Given: a reader supplying qualifying drives
    When: the emit callable runs
    Then: the `ltft-trend` SSOT is written and parses.
    """
    statesDir = str(tmp_path / "states")
    perDrive = {d: (None, _qualifyingDrive(-1.0)) for d in range(1, 6)}
    emit = makeLtftTrendEmitter(
        statesDir, driveRowsReader=lambda: perDrive, nowIsoFn=lambda: _NOW
    )

    emit()

    with open(os.path.join(statesDir, LTFT_TREND_FILENAME), encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["median"] == -1.0
    assert payload["ts"] == _NOW


def test_emitter_neverRaises_whenTheReaderFails(tmp_path):
    """
    Given: a reader that raises
    When: the emit callable runs
    Then: it swallows the failure -- the dashboard hook never blocks its owner.
    """
    def boom() -> dict:
        raise sqlite3.OperationalError("database is locked")

    emit = makeLtftTrendEmitter(str(tmp_path / "states"), driveRowsReader=boom)

    emit()  # must not raise


def test_emitter_warmingDrive_writesTypedAbsenceNotAnEmptyFile(tmp_path):
    """
    Given: a cold drive that never qualifies
    When: the emit callable runs
    Then: the file EXISTS and states the WARMING reason.

    An absent file renders "no data -- trend not computed", which is a different
    and less informative fact than "the engine has not warmed up yet".
    """
    statesDir = str(tmp_path / "states")
    perDrive = {1: (None, _warmDriveRows([5.0] * 30, coolant=40.0, fuelStatus=1.0))}
    emit = makeLtftTrendEmitter(
        statesDir, driveRowsReader=lambda: perDrive, nowIsoFn=lambda: _NOW
    )

    emit()

    with open(os.path.join(statesDir, LTFT_TREND_FILENAME), encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload["reason"] == REASON_WARMING
    assert payload["median"] is None


# ===========================================================================
# 10. THE CONTRACT'S OWN CONSTANTS -- grounded, not invented.
# ===========================================================================


def test_gateConstantsMatchSpoolsContract():
    """
    Given: the module's gate constants
    When: compared to specs/grounded-knowledge.md "LTFT trend contract (US-661)"
    Then: they match exactly.

    Pinned so a later "tidy-up" that rounds 85 to 80 or drops the window to 3
    drives has to argue with the measurement rather than a magic number.
    """
    assert GATE_COOLANT_MIN_C == 85.0
    assert FUEL_SYSTEM_CLOSED_LOOP == 2
    assert GATE_MIN_QUALIFYING_SAMPLES == 20
    assert TREND_MEDIAN_WINDOW == 5
