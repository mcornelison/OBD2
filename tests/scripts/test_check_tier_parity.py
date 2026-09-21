################################################################################
# File Name: test_check_tier_parity.py
# Purpose/Description: ARCH-038 -- the cross-tier parity check that would have
#   caught A-37 in its first week.
#
# WHAT A-37 WAS (measured 2026-09-16)
#   EDR persistence shipped 2026-07-01. The SERVER TABLES WERE NEVER CREATED.
#   `SHOW TABLES LIKE 'edr%'` on obd2db returned 0 rows while the Pi journal
#   purged ~1.77M rows/day, hourly, on an age-only rule. Six to ten weeks of
#   data recorded itself and deleted itself into a destination that did not
#   exist.
#
#   Every component worked correctly -- the reader read, the subscriber
#   persisted, the purge honoured its window. The defect lived in the SEAM,
#   which is exactly what component tests do not cover.
#
#   A destination sitting at ZERO for a producer writing MILLIONS is not a
#   subtle signal. Nobody was asking.
#
# WHY THE TEST READS THE REAL CONTRACT
#   The checker imports IN_SCOPE_TABLES rather than listing tables. A copied
#   list drifts, and a parity checker that has drifted from the contract it
#   checks is worse than no checker -- it reports green over the gap. These
#   tests assert the coupling, so adding a table to PK_COLUMN automatically
#   extends coverage.
#
# Author: Atlas (Architect) -- ARCH-038
# Creation Date: 2026-09-20
################################################################################

"""ARCH-038: verify the destination exists, not just that we sent."""

from __future__ import annotations

import pytest

from scripts.check_tier_parity import (
    EMPTY,
    MISSING,
    OK,
    UNKNOWN,
    UNUSED,
    TableState,
    checkTables,
    exitCodeFor,
)


class _FakeTier:
    """Injected accessor. Maps table -> TableState, or raises for unreachable."""

    def __init__(self, states: dict[str, TableState]) -> None:
        self._states = states

    def inspect(self, table: str) -> TableState:
        if table not in self._states:
            raise LookupError(f"no stub for {table}")
        return self._states[table]


def test_a_table_absent_from_the_server_is_MISSING() -> None:
    """🔴 This is A-37 on day one. The contract names it; the server lacks it."""
    tier = _FakeTier({"edr_imu_sample": TableState(exists=False, rows=None)})

    results = checkTables(["edr_imu_sample"], tier)

    assert results[0].verdict == MISSING


def test_destination_empty_while_the_PRODUCER_has_rows_is_EMPTY() -> None:
    """🔴 This is A-37 four weeks later -- table created, nothing arriving.

    EMPTY requires BOTH halves: a destination at zero AND a producer that has
    actually produced. That pairing is the whole signal.
    """
    tier = _FakeTier({"edr_light_sample": TableState(exists=True, rows=0)})
    producer = _FakeTier({"edr_light_sample": TableState(exists=True, rows=291_246)})

    results = checkTables(["edr_light_sample"], tier, producer=producer)

    assert results[0].verdict == EMPTY


def test_both_tiers_at_zero_is_UNUSED_not_a_defect() -> None:
    """🔴 The false positive this check produced on its FIRST real run.

    ai_recommendations, alert_log and calibration_sessions were all 0 on the
    server AND 0 on the Pi -- features that have simply never produced. Calling
    those defects is the "bare threshold inside the signal's normal operating
    range" anti-pattern this project has catalogued five times, and a check that
    cries wolf every run is one nobody reads on the day it matters.
    """
    tier = _FakeTier({"alert_log": TableState(exists=True, rows=0)})
    producer = _FakeTier({"alert_log": TableState(exists=True, rows=0)})

    results = checkTables(["alert_log"], tier, producer=producer)

    assert results[0].verdict == UNUSED


def test_destination_empty_with_NO_producer_information_is_UNKNOWN() -> None:
    """Without the producer, a zero destination is genuinely ambiguous.

    It is either A-37 or an unused feature, and the server alone cannot tell
    which. Saying UNKNOWN is honest; guessing either way is not.
    """
    tier = _FakeTier({"statistics": TableState(exists=True, rows=0)})

    results = checkTables(["statistics"], tier)  # no producer

    assert results[0].verdict == UNKNOWN


def test_UNUSED_does_not_fail_the_run() -> None:
    tier = _FakeTier({"a": TableState(exists=True, rows=0)})
    producer = _FakeTier({"a": TableState(exists=True, rows=0)})

    assert exitCodeFor(checkTables(["a"], tier, producer=producer)) == 0


def test_a_MISSING_destination_is_a_defect_even_when_the_producer_is_empty() -> None:
    """The contract names the table. Its absence is a defect regardless.

    A-37's first day looked exactly like this: the contract listed the EDR
    tables and the server had never created them.
    """
    tier = _FakeTier({"edr_imu_sample": TableState(exists=False, rows=None)})
    producer = _FakeTier({"edr_imu_sample": TableState(exists=True, rows=0)})

    results = checkTables(["edr_imu_sample"], tier, producer=producer)

    assert results[0].verdict == MISSING


def test_a_populated_table_is_OK() -> None:
    tier = _FakeTier({"realtime_data": TableState(exists=True, rows=24_682)})

    results = checkTables(["realtime_data"], tier)

    assert results[0].verdict == OK
    assert results[0].rows == 24_682


def test_an_unreachable_tier_is_UNKNOWN_and_never_zero() -> None:
    """🔴 A tier we could not read is NOT an empty tier.

    `specs/storage-retention-custody.md`: UNKNOWN is a TYPED ABSENCE and must
    never be rendered, summed or defaulted to 0. Conflating them is how a dead
    destination shows a green light.
    """
    tier = _FakeTier({"power_log": TableState(exists=None, rows=None)})

    results = checkTables(["power_log"], tier)

    assert results[0].verdict == UNKNOWN
    assert results[0].rows is None, "UNKNOWN must not carry a fabricated count"


def test_a_table_that_exists_with_an_unreadable_count_is_UNKNOWN() -> None:
    """Exists, but the count failed. Still undetermined -- not OK, not EMPTY."""
    tier = _FakeTier({"statistics": TableState(exists=True, rows=None)})

    results = checkTables(["statistics"], tier)

    assert results[0].verdict == UNKNOWN


def test_an_accessor_that_raises_becomes_UNKNOWN_not_a_crash() -> None:
    """One unreadable table must not stop the other fifteen being checked.

    Blast-radius lesson from the sync contract itself: a missing table raised
    out of pushAllDeltas and stopped ALL Pi->server sync until it was guarded.
    """

    class _Exploding:
        def inspect(self, table: str) -> TableState:
            if table == "boom":
                raise OSError("connection reset")
            return TableState(exists=True, rows=5)

    results = checkTables(["boom", "alert_log"], _Exploding())

    byName = {r.table: r for r in results}
    assert byName["boom"].verdict == UNKNOWN
    assert byName["alert_log"].verdict == OK, "one failure must not mask the rest"


# --- exit codes -------------------------------------------------------------


def test_exit_code_zero_only_when_everything_is_OK() -> None:
    tier = _FakeTier(
        {"a": TableState(exists=True, rows=1), "b": TableState(exists=True, rows=2)}
    )

    assert exitCodeFor(checkTables(["a", "b"], tier)) == 0


def test_a_definite_defect_exits_1() -> None:
    tier = _FakeTier(
        {"a": TableState(exists=True, rows=1), "b": TableState(exists=False, rows=None)}
    )

    assert exitCodeFor(checkTables(["a", "b"], tier)) == 1


def test_undetermined_exits_2_not_0() -> None:
    """🔴 UNKNOWN is not success.

    A cron that exits 0 because it could not reach the database is the inert
    guard this project keeps rediscovering: present, syntactically correct,
    enforcing nothing.
    """
    tier = _FakeTier(
        {"a": TableState(exists=True, rows=1), "b": TableState(exists=None, rows=None)}
    )

    assert exitCodeFor(checkTables(["a", "b"], tier)) == 2


def test_a_definite_defect_outranks_an_undetermined_one() -> None:
    tier = _FakeTier(
        {
            "a": TableState(exists=False, rows=None),
            "b": TableState(exists=None, rows=None),
        }
    )

    assert exitCodeFor(checkTables(["a", "b"], tier)) == 1


# --- the contract coupling --------------------------------------------------


def test_the_checker_reads_the_REAL_sync_contract() -> None:
    """🔴 The checker must not carry its own copy of the table list.

    A copied list drifts from the contract and then reports green over the very
    gap it exists to find. Adding a table to PK_COLUMN must extend coverage
    with no edit here.
    """
    from scripts.check_tier_parity import tablesUnderContract
    from src.pi.data.sync_log import IN_SCOPE_TABLES

    assert set(tablesUnderContract()) == set(IN_SCOPE_TABLES)


def test_the_edr_tables_are_under_contract() -> None:
    """The regression guard for A-37 specifically.

    If these ever leave the contract, this check stops watching the tables that
    silently deleted themselves -- and it would do so without failing.
    """
    from scripts.check_tier_parity import tablesUnderContract

    covered = set(tablesUnderContract())
    assert "edr_imu_sample" in covered
    assert "edr_light_sample" in covered


@pytest.mark.parametrize("bad", [None, "", 0])
def test_tables_must_be_named(bad: object) -> None:
    tier = _FakeTier({})
    with pytest.raises((TypeError, ValueError)):
        checkTables([bad], tier)  # type: ignore[list-item]
