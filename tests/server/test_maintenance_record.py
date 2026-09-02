################################################################################
# File Name: test_maintenance_record.py
# Purpose/Description: ARCH-020 -- the vehicle maintenance record's schema, seed
#                      data and loader. Every test here exists because a real
#                      row in the assembled 47-event record would break without
#                      it; none of them are shape-for-shape's-sake.
# Author: Atlas (Architect)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Atlas        | ARCH-020 initial -- written BEFORE the models,
#               |              | migration, seed file and loader exist.
# ================================================================================
################################################################################

"""Tests for the ``maintenance_log`` / ``maintenance_schedule`` contract.

Why these particular tests
--------------------------

The maintenance record is the first table in this project fed **entirely** by
humans and paper.  There is no odometer PID; every mileage figure is operator- or
shop-supplied.  So the failure modes are not sensor failure modes -- they are
provenance failure modes, and each test below pins one that the real 47-event
record actually contains:

* ``May 2025`` and ``~2022-26`` are not days.  A schema that cannot say so makes
  the loader invent one.
* Illinois emissions odometers are rounded to the nearest 1,000, which produces
  an apparent ROLLBACK (77,000 then 76,961 six months later).  Without a source
  tier that is unresolvable, and a naive integrity check calls a healthy car
  tampered.
* The timing belt has no service record in any of four sources.  Its only
  candidate is a 2008 "60,000 mile service" that never names a belt.  A schema
  that cannot distinguish *inferred* from *confirmed* reports that belt as done.

That last one is a safety property on an interference engine, not a data-quality
nicety.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def session():
    """A real SQLite session with the real metadata -- no mocks.

    SQLite enforces CHECK constraints, so the both-null-or-both-set rule and the
    at-least-one-interval rule are exercised for real rather than asserted about.
    """
    from src.server.db.models import Base

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seedRows() -> list[dict]:
    from src.server.data.maintenance_seed import loadSeedEvents

    return loadSeedEvents()


# ---- The date-precision contract ---------------------------------------------


def test_event_date_precision_has_no_default() -> None:
    """A row cannot acquire a precision by omission.

    ``May 2025`` (row 38) and the spark plugs (``~2022-26``) are not days.  If
    the column defaults, a loader that forgets to set it produces a row claiming
    day precision it never had -- and nothing downstream can tell.
    """
    from src.server.db.models import MaintenanceLog

    column = MaintenanceLog.__table__.columns['event_date_precision']
    assert column.default is None
    assert column.server_default is None
    assert not column.nullable


def test_month_precision_row_renders_as_a_month_not_a_day() -> None:
    """``May 2025`` must read back as ``May 2025``, never as ``2025-05-01``.

    The stored ``event_date`` is a sortable anchor.  The rendered value is what a
    human or an agent quotes, and it must not add a day the record never had.
    """
    from datetime import date

    from src.server.db.models import formatEventDate

    rendered = formatEventDate(date(2025, 5, 1), 'month', None)

    assert rendered == 'May 2025'
    assert '05-01' not in rendered


def test_range_precision_row_renders_both_ends() -> None:
    """The spark plugs are a four-year window and must read as one."""
    from datetime import date

    from src.server.db.models import formatEventDate

    rendered = formatEventDate(date(2022, 1, 1), 'range', date(2026, 1, 1))

    assert '2022' in rendered
    assert '2026' in rendered


# ---- The odometer-provenance contract ----------------------------------------


def test_odometer_without_a_source_is_rejected(session) -> None:
    """A mileage with no stated origin cannot be landed.

    There is no odometer PID on this vehicle.  Every figure is human- or
    shop-entered, so an unattributed number is indistinguishable from a guess.
    """
    from src.server.db.models import MaintenanceLog

    session.add(
        MaintenanceLog(
            event_date=_date('2026-08-22'),
            event_date_precision='day',
        event_date_certainty='exact',
            odometer_mi=78907,
            odometer_source=None,
            work_performed='oil + filter',
            provenance='odometer: CIO-declared',
            recorded_by='test',
        ),
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_odometer_source_without_a_reading_is_rejected(session) -> None:
    """The converse: a source column claiming provenance for no value."""
    from src.server.db.models import MaintenanceLog

    session.add(
        MaintenanceLog(
            event_date=_date('2026-08-22'),
            event_date_precision='day',
        event_date_certainty='exact',
            odometer_mi=None,
            odometer_source='shop_record',
            work_performed='oil + filter',
            provenance='no odometer captured',
            recorded_by='test',
        ),
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_2022_apparent_rollback_is_resolvable_from_the_source_tiers(
    session,
) -> None:
    """77,000 then 76,961 six months later is NOT a rollback -- and must prove it.

    2022-04-12 is a state-agency emissions reading rounded to the nearest 1,000.
    2022-10-11 is an exact shop record.  The rounding manufactures the apparent
    reversal.  A consumer must be able to establish that from the stored tiers
    alone, without reading a note.
    """
    from src.server.db.models import MaintenanceLog, isRoundedOdometer

    earlier = MaintenanceLog(
        event_date=_date('2022-04-12'),
        event_date_precision='day',
        event_date_certainty='exact',
        odometer_mi=77000,
        odometer_source='state_agency_rounded',
        work_performed='Emissions PASS',
        provenance='odometer: state agency, rounded to nearest 1000',
        recorded_by='test',
    )
    later = MaintenanceLog(
        event_date=_date('2022-10-11'),
        event_date_precision='day',
        event_date_certainty='exact',
        odometer_mi=76961,
        odometer_source='shop_record',
        work_performed='tyres rotated; oil + filter',
        provenance='odometer: shop record, exact',
        recorded_by='test',
    )
    session.add_all([earlier, later])
    session.flush()

    assert later.odometer_mi < earlier.odometer_mi
    assert isRoundedOdometer(earlier.odometer_source)
    assert not isRoundedOdometer(later.odometer_source)


# ---- The schedule contract ---------------------------------------------------


def test_schedule_row_needs_at_least_one_interval(session) -> None:
    """A due-item with no interval of any kind can never fire."""
    from src.server.db.models import MaintenanceSchedule

    session.add(
        MaintenanceSchedule(
            item='spark plugs',
            interval_miles=None,
            interval_months=None,
            interval_engine_hours=None,
            last_done_confidence='unknown',
            recorded_by='test',
        ),
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_calendar_only_interval_is_legal(session) -> None:
    """At ~500 mi/yr, a 60,000-mile interval takes 120 years.

    Only calendar intervals can ever fire on this car, so a months-only row must
    be a first-class citizen rather than an incomplete one.
    """
    from src.server.db.models import MaintenanceSchedule

    session.add(
        MaintenanceSchedule(
            item='timing belt',
            interval_miles=60000,
            interval_months=60,
            interval_engine_hours=None,
            last_done_confidence='inferred',
            recorded_by='test',
        ),
    )
    session.flush()  # must not raise


def test_last_done_confidence_has_no_default() -> None:
    """Confidence must be stated, because the belt's is the unusual value.

    If this defaults to ``confirmed``, the single most dangerous row in the
    record acquires the safest value by omission.
    """
    from src.server.db.models import MaintenanceSchedule

    column = MaintenanceSchedule.__table__.columns['last_done_confidence']
    assert column.default is None
    assert column.server_default is None
    assert not column.nullable


# ---- The seed data itself ----------------------------------------------------


def test_seed_file_is_version_controlled_json_in_the_repo() -> None:
    """The record must not live only on a share that has no undo.

    2026-09-01: the NAS volume is ext4, Synology snapshots require Btrfs, and
    none were ever taken.  In S41 the only surviving copy of a truncated file was
    the copy that lived in the database.
    """
    path = PROJECT_ROOT / 'src' / 'server' / 'data' / 'maintenance_seed_2026-09-01.json'
    assert path.exists()
    json.loads(path.read_text(encoding='utf-8'))


def test_seed_holds_the_47_dated_events_plus_the_one_undated_item() -> None:
    """47 DATED events, numbered 1-47, plus the spark plugs as seq 48.

    Spool's canonical count is "47 dated events", and the spark plugs are
    explicitly "the only maintenance item with NO date at all" -- an owner
    recollection of a four-year window, not a source-recorded date.  So the plugs
    sit OUTSIDE his numbering rather than renumbering his record, but they still
    belong in the log: the work really happened, and dropping the row to make a
    count come out would lose that fact.

    48 rows, 47 of them dated.  Stated here so the difference can never be read
    as an off-by-one.
    """
    events = _seedRows()

    assert len(events) == 48
    assert {e['seq'] for e in events} == set(range(1, 49))
    assert len([e for e in events if e['seq'] <= 47]) == 47


def test_every_seed_event_states_its_date_precision() -> None:
    for event in _seedRows():
        assert event['event_date_precision'] in {'day', 'month', 'year', 'range'}


def test_every_seed_odometer_declares_a_source() -> None:
    """The both-null-or-both-set rule, checked against the real data."""
    for event in _seedRows():
        hasReading = event.get('odometer_mi') is not None
        hasSource = event.get('odometer_source') is not None
        assert hasReading == hasSource, event


def test_seed_carries_every_odometer_reading_the_master_table_states() -> None:
    """26 readings -- and Spool's summary says 27.  ROUTED, not reconciled.

    The master table as supplied carries 26 distinct odometer readings.  The
    accompanying prose says 27.  I have counted the supplied table three times and
    get 26; the discrepancy is either a miscount in the summary or a reading
    present in the full card that did not survive into the rendering I was given.

    ⚠️ I am NOT inventing a 27th to make the number agree.  Manufacturing a
    reading to satisfy a stated count is precisely the failure this table exists
    to prevent, and an odometer is an ANCHOR: a wrong one is a permanent offset on
    every derived mileage forever, with no sensor able to catch it.  A transposed
    78,097-for-78,907 already happened once on this project.

    This test asserts what the data actually contains.  If Spool confirms a 27th,
    it lands as a seed edit and this number moves WITH the evidence.
    """
    readings = [e for e in _seedRows() if e.get('odometer_mi') is not None]

    assert len(readings) == 26


def test_the_odometer_anchor_is_78907_not_78097() -> None:
    """The transposition that already happened once, guarded.

    78,907 @ 2026-08-22 is the CIO-declared anchor. 78,097 was filed in US-643 and
    corrected. Nothing downstream can detect this error, so it is guarded here.
    """
    events = _seedRows()
    anchor = [e for e in events if e['event_date'] == '2026-08-22']

    assert len(anchor) == 1
    assert anchor[0]['odometer_mi'] == 78907


def test_seed_preserves_the_verbatim_shop_wording_for_the_pcm_reset() -> None:
    """Carfax normalised "Reset PCM memory" into "Computer reprogrammed".

    That flattening manufactured a conflict with the prior ECU's never-flashed
    status which stood as unresolvable until the primary document was read.  The
    verbatim wording must survive into the table.
    """
    events = _seedRows()
    pcm = [e for e in events if e.get('dtc_code') == 'P0134']

    assert len(pcm) == 1
    assert 'Reset PCM memory' in (pcm[0].get('source_verbatim') or '')


def test_seed_marks_the_epoch_boundaries() -> None:
    """ECU swap, O2 sensor, adaptive reset and oil change all break comparison."""
    events = _seedRows()
    boundaries = [e for e in events if e.get('is_epoch_boundary')]

    assert len(boundaries) >= 4


def test_no_seed_event_claims_a_COMPLETED_timing_belt_service() -> None:
    """Four independent sources; not one of them names a belt service. Ever.

    The 2026-09-02 appointment legitimately mentions the belt, so the guard is
    scoped to COMPLETED work: any row naming the belt must be marked SCHEDULED.
    That keeps it meaningful rather than merely passing -- a completed belt row
    added by a future edit still trips it.
    """
    for event in _seedRows():
        text = f"{event.get('work_performed', '')} {event.get('source_verbatim') or ''}"
        if 'timing belt' in text.lower():
            assert 'SCHEDULED' in event['work_performed'], (
                f"event {event['seq']} names a timing belt as completed work. No "
                f'source in four independent records has ever done so.'
            )


# ---- The loader --------------------------------------------------------------


def test_loader_lands_every_seed_event(session) -> None:
    from src.server.data.maintenance_seed import loadSeedIntoSession
    from src.server.db.models import MaintenanceLog

    loadSeedIntoSession(session)

    count = len(session.execute(select(MaintenanceLog)).scalars().all())
    assert count == 48


def test_loader_is_idempotent(session) -> None:
    """Re-running the one-time load must not duplicate the record."""
    from src.server.data.maintenance_seed import loadSeedIntoSession
    from src.server.db.models import MaintenanceLog

    loadSeedIntoSession(session)
    loadSeedIntoSession(session)

    count = len(session.execute(select(MaintenanceLog)).scalars().all())
    assert count == 48


def test_loaded_timing_belt_schedule_reads_inferred_not_confirmed(session) -> None:
    """The safety property, end to end.

    The belt's only candidate is the 2008 "60,000 mile service", which names no
    belt.  After the load, a consumer asking "when was the belt done" must get
    an answer that is marked as an inference -- never as a service record.
    """
    from src.server.data.maintenance_seed import loadSeedIntoSession
    from src.server.db.models import MaintenanceSchedule

    loadSeedIntoSession(session)

    belt = session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.item == 'timing belt'),
    ).scalar_one()

    assert belt.last_done_confidence == 'inferred'
    assert belt.interval_months == 60


def test_loaded_spark_plugs_schedule_reads_unknown(session) -> None:
    """The only item in the record with no date at all must say so."""
    from src.server.data.maintenance_seed import loadSeedIntoSession
    from src.server.db.models import MaintenanceSchedule

    loadSeedIntoSession(session)

    plugs = session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.item == 'spark plugs'),
    ).scalar_one()

    assert plugs.last_done_confidence == 'unknown'


# ---- Helpers -----------------------------------------------------------------


def _date(iso: str):
    from datetime import date

    return date.fromisoformat(iso)


def test_same_year_range_renders_months_not_a_repeated_year() -> None:
    """A 1999-02 -> 1999-06 window must not read as ``1999-1999``.

    Six of the 48 rows are Carfax windows that open and close inside one year.
    Rendering those as a repeated year reads as a typo, and a reader who assumes
    it IS a typo will silently treat the row as a single-day event -- which is
    the false precision the precision column exists to prevent, reintroduced at
    the display layer.
    """
    from datetime import date

    from src.server.db.models import formatEventDate

    rendered = formatEventDate(date(1999, 2, 1), 'range', date(1999, 6, 30))

    assert rendered == 'Feb-Jun 1999'
    assert '1999-1999' not in rendered


# ---- The date-CERTAINTY contract (CIO 2026-09-02) ----------------------------
#
# Precision and certainty are ORTHOGONAL and conflating them loses information.
# Precision says how fine-grained the date is. Certainty says whether a source
# RECORDED it or somebody ESTIMATED it. The case that proves they are different
# is seed row 3: it stores 1999-04-01 for the second of three services inside a
# Carfax window, and that date is an INTERPOLATION invented to sort the row.
# Precision 'range' flags the granularity; nothing distinguished the invented
# anchor from 2008-05-08, which a dealer actually wrote down.


def test_event_date_certainty_has_no_default() -> None:
    """Certainty must be stated, for the same reason precision must be.

    A defaulting column lets a row acquire 'exact' by omission, and 'exact' is
    the load-bearing value: it is the one a consumer trusts.
    """
    from src.server.db.models import MaintenanceLog

    column = MaintenanceLog.__table__.columns['event_date_certainty']
    assert column.default is None
    assert column.server_default is None
    assert not column.nullable


def test_a_non_day_precision_cannot_be_marked_exact(session) -> None:
    """'May 2025' marked exact is a contradiction, and the DB must refuse it.

    A month-, year- or range-precision row stores an anchor whose finer
    components were invented by the loader. Calling that exact would state a day
    no source ever gave -- which is the whole defect the precision column exists
    to prevent, re-entering through the certainty column.
    """
    from src.server.db.models import MaintenanceLog

    session.add(
        MaintenanceLog(
            event_date=_date('2025-05-01'),
            event_date_precision='month',
            event_date_certainty='exact',
            work_performed='Cold air intake',
            provenance='owner reported, month only',
            recorded_by='test',
        ),
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_day_precision_row_may_still_be_estimated(session) -> None:
    """The converse is NOT forbidden, and that is the point of the column.

    Someone recalling a specific day with confidence gives day precision and
    estimated certainty. If certainty were merely derived from precision, that
    row would be indistinguishable from a dealer record.
    """
    from src.server.db.models import MaintenanceLog

    session.add(
        MaintenanceLog(
            event_date=_date('2025-06-19'),
            event_date_precision='day',
            event_date_certainty='estimated',
            work_performed='Coilovers',
            provenance='owner recollection of a specific day',
            recorded_by='test',
        ),
    )
    session.flush()  # must not raise


def test_every_seed_event_states_its_date_certainty() -> None:
    for event in _seedRows():
        assert event['event_date_certainty'] in {'exact', 'estimated'}, event


def test_the_may_2025_row_is_estimated() -> None:
    """The CIO's own worked example."""
    events = _seedRows()
    row = next(e for e in events if e['seq'] == 38)

    assert row['event_date_precision'] == 'month'
    assert row['event_date_certainty'] == 'estimated'


def test_the_interpolated_window_rows_are_estimated() -> None:
    """Seq 3's 1999-04-01 is mine, not any source's. It must say so."""
    events = _seedRows()
    row = next(e for e in events if e['seq'] == 3)

    assert row['event_date_certainty'] == 'estimated'


def test_a_dealer_recorded_day_is_exact() -> None:
    """Seq 17, the belt candidate. Its DATE is exact even though the work is not."""
    events = _seedRows()
    row = next(e for e in events if e['seq'] == 17)

    assert row['event_date_precision'] == 'day'
    assert row['event_date_certainty'] == 'exact'


def test_no_seed_row_claims_exact_on_a_non_day_precision() -> None:
    """The invariant, checked against the real 48 rows rather than in principle."""
    for event in _seedRows():
        if event['event_date_precision'] != 'day':
            assert event['event_date_certainty'] == 'estimated', event


def test_same_month_range_renders_one_month_not_a_repeated_one() -> None:
    """A 2024-08-01 -> 2024-08-31 window must read 'Aug 2024', not 'Aug-Aug 2024'.

    Same reasoning as the same-year case: a repeated component reads as a
    rendering bug, and a reader who dismisses it as one stops trusting the rest
    of the line.
    """
    from datetime import date

    from src.server.db.models import formatEventDate

    rendered = formatEventDate(date(2024, 8, 1), 'range', date(2024, 8, 31))

    assert rendered == 'Aug 2024'
