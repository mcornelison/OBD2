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
