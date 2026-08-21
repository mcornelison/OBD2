################################################################################
# File Name: test_us390_attribution_backstop.py
# Purpose/Description: US-390 (F-107) AC#2 -- server-side belt-and-suspenders
#                      backstop confirmation.  Proves that even if a future Pi
#                      DriveDetector regression re-emits two overlapping
#                      drive_ids for one physical leg (the drives-28/29
#                      signature this sprint exists to fix), the server tripwire
#                      still catches it: detect_overlapping_drives flags the
#                      overlap and compute_drive_summary stamps
#                      data_quality='attribution_anomaly' on the row.  Anchors
#                      the prior-sprint detector/CLI coverage to THIS sprint's
#                      28/29 signature.
# Author: Rex (Ralph agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-390) | Initial -- synthetic drives-28/29 residual
#                               overlap drives the full server tripwire path;
#                               asserts attribution_anomaly stamped + a clean
#                               control stamps 'full'.  Real ORM + real INSERTs
#                               (post-I-040 discipline); no compute-seam mocks.
# ================================================================================
################################################################################

"""US-390 AC#2 -- the server tripwire is the backstop for a Pi regression.

US-388 fixes the Pi DriveDetector so drives 28/29 cannot recur.  US-390 is the
belt-and-suspenders: if that Pi fix ever regresses and two overlapping
``drive_id``s are emitted for one physical leg again, the server must STILL
catch it.  The server detector is ``detect_overlapping_drives`` (US-362, pure
query over raw ``realtime_data``); the SSOT stamping path is
``compute_drive_summary``, which sets ``data_quality='attribution_anomaly'``
whenever the detector reports an overlap (US-363, observability not refusal --
the row is still written and fully readable, only flagged).

These tests model the *residual 28/29 signature* explicitly (vs the prior
sprints' 23/24 fixtures) and confirm the backstop end-to-end:

* ``test_residualOverlap2829_detector_andComputeStamp_anomaly`` -- drives 28 +
  29 share a window; the detector reports the overlap AND the compute path
  stamps the anomaly on drive 28's row.
* ``test_cleanDrive_noOverlap_stampsFull`` -- the discriminating control: a
  cleanly-separated drive is stamped ``full`` (so the anomaly assertion above
  is meaningful, not a constant).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.drive_summary_compute import (  # noqa: E402
    compute_drive_summary,
)
from src.server.analytics.overlap import detect_overlapping_drives  # noqa: E402
from src.server.db.models import (  # noqa: E402
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DRIVE_SUMMARY_DATA_QUALITY_FULL,
    Base,
    DriveSummary,
    RealtimeData,
)

# Drives 28/29 -- the live signature this sprint (A-9 recurrence) exists to fix.
_DRIVE_A = 28
_DRIVE_B = 29
_CLEAN_DRIVE = 31
_CLEAN_NEIGHBOUR = 32

# Anchored on the drives-28/29 incident date (2026-06-06) for readability; the
# absolute value is immaterial, only the relative windows matter.
_BASE_TS = datetime(2026, 6, 6, 8, 0, 0)


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedDriveSummary(session: Session, *, driveId: int) -> int:
    """Seed a Pi-sync drive_summary row with NULL analytics columns.

    Mirrors the production state before the server compute runs: Pi event-log
    columns present, derived analytics (including ``data_quality``) NULL.
    Returns the server-side ``drive_summary.id``.
    """
    row = DriveSummary(
        source_device="chi-eclipse-01",
        source_id=driveId,
        drive_id=driveId,
        data_source="real",
    )
    session.add(row)
    session.flush()
    return int(row.id)


def _seedRealtimeWindow(
    session: Session,
    *,
    driveId: int,
    startTime: datetime,
    samples: int,
    pollIntervalSeconds: int = 1,
) -> None:
    """Seed ``samples`` RPM rows so the drive's MIN/MAX window is exact."""
    cursor = driveId * 1_000_000
    for i in range(samples):
        session.add(
            RealtimeData(
                source_id=cursor + i,
                source_device="chi-eclipse-01",
                timestamp=startTime + timedelta(seconds=i * pollIntervalSeconds),
                parameter_name="RPM",
                value=2000.0,
                drive_id=driveId,
                data_source="real",
            )
        )


class TestResidual2829ServerBackstop:
    """The server tripwire flags a residual drives-28/29 overlap end-to-end."""

    def test_residualOverlap2829_detector_andComputeStamp_anomaly(self, engine):
        """Drives 28+29 overlap -> detector reports it AND row stamped anomaly.

        Models a residual Pi regression: one physical leg minted twice (28 then
        29, windows intersecting).  Asserts BOTH layers of the backstop -- the
        SSOT detector (detect_overlapping_drives) and the stamping consumer
        (compute_drive_summary) -- so the anomaly cannot slip through.
        """
        with Session(engine) as session:
            sid = _seedDriveSummary(session, driveId=_DRIVE_A)
            # Drive 28: 08:00:00 .. 08:02:00 (121 one-second samples).
            _seedRealtimeWindow(
                session, driveId=_DRIVE_A, startTime=_BASE_TS, samples=121,
            )
            # Drive 29: 08:01:00 .. 08:03:00 -- overlaps drive 28 by ~1 minute
            # (the same physical leg emitted under two drive_ids).
            _seedRealtimeWindow(
                session, driveId=_DRIVE_B,
                startTime=_BASE_TS + timedelta(seconds=60), samples=121,
            )
            session.commit()

            # Layer 1: the SSOT detector sees the overlap from raw realtime_data.
            assert detect_overlapping_drives(session, _DRIVE_A) == [_DRIVE_B]

            # Layer 2: the compute path stamps the anomaly on the summary row.
            assert compute_drive_summary(session, _DRIVE_A) == sid
            session.commit()
            assert (
                session.get(DriveSummary, sid).data_quality
                == DATA_QUALITY_ATTRIBUTION_ANOMALY
            )

    def test_cleanDrive_noOverlap_stampsFull(self, engine):
        """Control: a cleanly-separated drive -> data_quality default ('full').

        Discriminating case -- proves the anomaly stamp above is driven by the
        overlap, not a constant the backstop would emit for every drive.
        """
        with Session(engine) as session:
            sid = _seedDriveSummary(session, driveId=_CLEAN_DRIVE)
            _seedRealtimeWindow(
                session, driveId=_CLEAN_DRIVE, startTime=_BASE_TS, samples=60,
            )
            # Neighbour starts 5 minutes later -- no shared second.
            _seedRealtimeWindow(
                session, driveId=_CLEAN_NEIGHBOUR,
                startTime=_BASE_TS + timedelta(seconds=300), samples=60,
            )
            session.commit()

            assert detect_overlapping_drives(session, _CLEAN_DRIVE) == []
            assert compute_drive_summary(session, _CLEAN_DRIVE) == sid
            session.commit()
            # US-563 repointed this constant, and the repoint MATTERS here: the
            # assertion is that compute stamped the clean VERDICT, and it used
            # to be spelled with a constant named "..._DEFAULT".  Under the new
            # split that name means the non-verdict 'unassessed', so leaving it
            # would have turned this into "compute left the row untouched" --
            # green for the wrong reason on a drive it had just assessed.
            assert (
                session.get(DriveSummary, sid).data_quality
                == DRIVE_SUMMARY_DATA_QUALITY_FULL
            )
