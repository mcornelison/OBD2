################################################################################
# File Name: calibration.py
# Purpose/Description: Baseline calibration analytics — compares real-drive
#                      statistics against sim baselines and proposes updates
#                      for CIO review.  The sole writer of the ``baselines``
#                      table (via :func:`applyCalibration`).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-162 (Sprint 9) —
#               |              | pure proposeCalibration + atomic
#               |              | applyCalibration. No ingest path changes.
# ================================================================================
################################################################################

"""
Baseline calibration analytics.

US-162 / spec §3.3: once the CIO has driven enough real OBD-II miles, the
sim-derived baselines that shipped during crawl/walk drift from the Eclipse's
actual steady-state values. This module computes the drift and proposes
updates, **never** mutating stored baselines without explicit approval.

Two entry points:

* :func:`proposeCalibration` — pure read. Aggregates real-drive statistics
  into per-parameter averages, compares them to the sim baseline (averaged
  from sim drives), and returns a :class:`ProposalResult` containing the
  real-drive count and one :class:`BaselineProposal` per parameter whose
  absolute percentage delta exceeds the configurable threshold.
* :func:`applyCalibration` — the only writer. Upserts each proposal into
  ``baselines`` by ``(device_id, parameter_name)``. Idempotent — replaying
  the same proposals produces identical state.

The ``--calibrate``/``--apply`` CLI wiring lives in :mod:`scripts.report`.
This module has no CLI, no printing, no logging — it's kept small and pure
so the CLI formatting (which is the bulk of the user-visible surface) can
be tested without touching the analytics itself.

"Real" drives are identified by ``DriveSummary.is_real=True``. See the
pre-flight audit in ``offices/ralph/progress.txt`` for the rationale
(boolean flag vs. ``profile_id`` convention).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.server.db.models import Baseline, DriveStatistic, DriveSummary

# ---- Constants ---------------------------------------------------------------

# Minimum real drives before :func:`proposeCalibration` returns proposals.
# Matches server spec §3.3 grounding ref (``CALIBRATION_MIN_DRIVES=5``).
MIN_REAL_DRIVES: int = 5

# Default percentage threshold (as a fraction, not percent). Parameters whose
# |real - sim| / |sim| falls at or below this value keep their sim baseline.
# Spec §3.3 calls out 2% as the meaningful-divergence floor.
DEFAULT_DELTA_THRESHOLD: float = 0.02


# ---- Result types ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineProposal:
    """One parameter's proposed baseline update.

    The ``action`` string is always either ``"UPDATE"`` or ``"KEEP"``;
    :func:`proposeCalibration` filters out ``KEEP`` rows so the CLI only
    renders actionable deltas, but the field is kept so tests (and future
    reports that want to show "no change") can distinguish the cases.
    """

    parameter_name: str
    sim_value: float
    real_value: float
    delta: float
    action: str
    min_value: float
    max_value: float
    std_dev: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class ProposalResult:
    """Return envelope for :func:`proposeCalibration`.

    Carries the real-drive count independently of the proposals list so the
    CLI can render the "Need N more real drives" banner without having to
    re-query the database.
    """

    realDriveCount: int
    proposals: list[BaselineProposal]


# ---- Public API --------------------------------------------------------------


def countRealDrives(session: Session, deviceId: str | None = None) -> int:
    """
    Return the number of ``is_real=True`` drives, optionally filtered by device.

    Args:
        session: Open SQLAlchemy session.
        deviceId: Optional device filter. When ``None``, counts across every
            registered device.

    Returns:
        Real-drive count.
    """
    stmt = select(DriveSummary.id).where(DriveSummary.is_real.is_(True))
    if deviceId is not None:
        stmt = stmt.where(DriveSummary.device_id == deviceId)
    return len(session.execute(stmt).all())


def proposeCalibration(
    session: Session,
    deviceId: str | None = None,
    *,
    deltaThreshold: float = DEFAULT_DELTA_THRESHOLD,
    minDrives: int = MIN_REAL_DRIVES,
) -> ProposalResult:
    """
    Compute proposed baseline updates from real-drive statistics.

    Reads every ``drive_statistics`` row whose owning ``drive_summary`` has
    ``is_real=True`` (and matches ``deviceId`` when provided), groups by
    ``parameter_name``, and averages ``avg_value`` for both real and sim
    buckets. Proposals are only returned for parameters whose real-vs-sim
    delta exceeds ``deltaThreshold`` and that have enough real drives overall.

    Args:
        session: Open SQLAlchemy session.
        deviceId: Optional device filter — calibration baselines are
            per-device, so the CLI always supplies this in practice. Passing
            ``None`` aggregates across devices (useful for ad-hoc exploration
            but not the supported ``--apply`` flow).
        deltaThreshold: Fractional threshold (default ``0.02`` → 2%).
        minDrives: Minimum real-drive count before proposals are emitted.

    Returns:
        :class:`ProposalResult`. ``proposals`` is always empty when
        ``realDriveCount < minDrives``.
    """
    realDriveCount = countRealDrives(session, deviceId=deviceId)
    if realDriveCount < minDrives:
        return ProposalResult(realDriveCount=realDriveCount, proposals=[])

    realStats = _collectStatsByParameter(session, deviceId, isReal=True)
    simStats = _collectStatsByParameter(session, deviceId, isReal=False)

    proposals: list[BaselineProposal] = []
    for paramName in sorted(realStats.keys()):
        realRows = realStats[paramName]
        simRows = simStats.get(paramName, [])
        if not realRows or not simRows:
            # Need both baselines to compare. A parameter that only exists in
            # real data (or only in sim) isn't a "drift" — it's a new series,
            # outside this story's scope.
            continue

        realAvgs = [row[0] for row in realRows]
        simAvgs = [row[0] for row in simRows]
        realAvg = float(statistics.fmean(realAvgs))
        simAvg = float(statistics.fmean(simAvgs))
        delta = realAvg - simAvg

        if simAvg == 0.0:
            # Avoid div-by-zero. Treat any non-zero delta from a zero sim
            # baseline as above threshold.
            relative = float("inf") if delta != 0.0 else 0.0
        else:
            relative = abs(delta) / abs(simAvg)

        action = "UPDATE" if relative > deltaThreshold else "KEEP"
        if action == "KEEP":
            continue

        # Envelope: min-of-mins / max-of-maxes keeps the baseline as the
        # widest observed range across real drives. Std is averaged across
        # real drives — per-drive within-drive variation.
        realMin = float(min(row[1] for row in realRows))
        realMax = float(max(row[2] for row in realRows))
        realStd = float(statistics.fmean([row[3] for row in realRows]))

        proposals.append(
            BaselineProposal(
                parameter_name=paramName,
                sim_value=simAvg,
                real_value=realAvg,
                delta=delta,
                action=action,
                min_value=realMin,
                max_value=realMax,
                std_dev=realStd,
                sample_count=len(realRows),
            )
        )

    return ProposalResult(realDriveCount=realDriveCount, proposals=proposals)


def applyCalibration(
    session: Session,
    proposals: list[BaselineProposal],
    deviceId: str,
) -> int:
    """
    Upsert each proposal into ``baselines`` under ``(device_id, parameter_name)``.

    Idempotent: existing rows are mutated in place, new rows are inserted.
    Caller is responsible for committing the session.

    Args:
        session: Open SQLAlchemy session.
        proposals: List produced by :func:`proposeCalibration`. An empty
            list is a no-op and returns ``0``.
        deviceId: Device these baselines belong to. Required because every
            ``baselines`` row is scoped to one device — never apply without
            an explicit device.

    Returns:
        Number of rows written (inserted + updated).
    """
    written = 0
    for proposal in proposals:
        existing = session.execute(
            select(Baseline).where(
                and_(
                    Baseline.device_id == deviceId,
                    Baseline.parameter_name == proposal.parameter_name,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                Baseline(
                    device_id=deviceId,
                    parameter_name=proposal.parameter_name,
                    avg_value=proposal.real_value,
                    min_value=proposal.min_value,
                    max_value=proposal.max_value,
                    std_dev=proposal.std_dev,
                    sample_count=proposal.sample_count,
                )
            )
        else:
            existing.avg_value = proposal.real_value
            existing.min_value = proposal.min_value
            existing.max_value = proposal.max_value
            existing.std_dev = proposal.std_dev
            existing.sample_count = proposal.sample_count
        written += 1

    return written


# ---- Internals ---------------------------------------------------------------


def _collectStatsByParameter(
    session: Session,
    deviceId: str | None,
    *,
    isReal: bool,
) -> dict[str, list[tuple[float, float, float, float]]]:
    """
    Fetch drive_statistics rows for drives matching the ``is_real`` filter.

    Returns a map ``parameter_name -> [(avg, min, max, std), ...]`` with one
    tuple per contributing drive, which the caller can average however it
    likes (avg/min/max/std are already per-drive aggregates at this layer).
    """
    filters = [DriveSummary.is_real.is_(isReal)]
    if deviceId is not None:
        filters.append(DriveSummary.device_id == deviceId)

    stmt = (
        select(
            DriveStatistic.parameter_name,
            DriveStatistic.avg_value,
            DriveStatistic.min_value,
            DriveStatistic.max_value,
            DriveStatistic.std_dev,
        )
        .join(DriveSummary, DriveSummary.id == DriveStatistic.drive_id)
        .where(and_(*filters))
    )

    buckets: dict[str, list[tuple[float, float, float, float]]] = {}
    for name, avgV, minV, maxV, stdV in session.execute(stmt).all():
        if avgV is None:
            continue
        buckets.setdefault(name, []).append(
            (
                float(avgV),
                float(minV if minV is not None else avgV),
                float(maxV if maxV is not None else avgV),
                float(stdV if stdV is not None else 0.0),
            )
        )
    return buckets


# ---- Public API --------------------------------------------------------------

__all__ = [
    "DEFAULT_DELTA_THRESHOLD",
    "MIN_REAL_DRIVES",
    "BaselineProposal",
    "ProposalResult",
    "applyCalibration",
    "countRealDrives",
    "proposeCalibration",
]
