################################################################################
# File Name: prior_shutdown_summary.py
# Purpose/Description: US-728 -- the operator surface for the prior-shutdown
#   verdict. ``boot_progress.arm`` has derived a positive-proof verdict from the
#   fdatasync'd breadcrumb trail and written it to ``startup_log`` on every boot
#   since 2026-08-25; the table is synced (US-417) and was read by nothing an
#   operator could see. This module READS that row and renders it. It writes
#   nothing: no second shutdown-marker producer, no new table, no writer change.
#
#   Honest-instrument rules this rendering obeys (US-728 acceptance):
#     * WHEN is a typed absence. ``prior_last_entry_ts`` is inserted as NULL by
#       construction (``boot_progress._writeStartupLogRow``); the RUNNING rung is
#       stamped at BOOT START, so it is not an end time either. The next boot's
#       ``recorded_at`` is carried ONLY as ``notAfterTs`` -- an upper bound.
#     * ``crashed_during_operation`` renders as "ended without a recorded
#       shutdown", never "crashed": powerwatch powers off without writing a
#       rung, so a death inside its pipeline and an undetected power cut read
#       identically. The surface does not claim WHERE the run ended.
#     * Every ``_VERDICT_BY_STAGE`` reason keeps its own text -- no collapse to
#       clean/unclean. An unrecognised code travels verbatim.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-13    | Ralph (Rex)  | Initial -- US-728 prior-shutdown surface.
# ================================================================================
################################################################################
"""Prior-shutdown verdict reader + renderer (US-728). Read-only."""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "CAVEAT_UNGRACEFUL",
    "END_TIME_ABSENT",
    "NOT_AFTER_LABEL",
    "NOT_READ_LINE",
    "VERDICT_CLEAN",
    "VERDICT_NO_RECORD",
    "VERDICT_UNGRACEFUL",
    "PriorShutdownSummary",
    "computePriorShutdownSummary",
    "formatPriorShutdownLine",
    "main",
    "readPriorShutdownSummaryFromPath",
]

VERDICT_CLEAN = "clean"
VERDICT_UNGRACEFUL = "ungraceful"
VERDICT_NO_RECORD = "no_record"

#: The typed absence for the end time -- the live condition on every row.
END_TIME_ABSENT = "end time not recorded"

#: How ``notAfterTs`` must always be introduced: it is the NEXT boot's write.
NOT_AFTER_LABEL = "next boot recorded (upper bound)"

#: The true limitation of the instrument (the old journal caveat was false).
CAVEAT_UNGRACEFUL = (
    "a graceful poweroff whose CLEAN_COMPLETE write did not land also reads "
    "as ungraceful"
)

#: Rendered when no row could be read at all -- a different fact from NO RECORD.
NOT_READ_LINE = "Previous shutdown: not read (no startup_log row available)"

#: Operator text per reason code boot_progress writes. Keyed by the stored
#: string, not by Stage, so historical rows render as themselves.
_REASON_TEXT: dict[str, str] = {
    "graceful": "CLEAN",
    "poweroff_accepted_unfinalized":
        "UNGRACEFUL: poweroff accepted, shutdown never finalized",
    "poweroff_invoked_never_returned":
        "UNGRACEFUL: poweroff invoked, never returned",
    "wedged_before_poweroff": "UNGRACEFUL: stopped before poweroff was invoked",
    "died_mid_drain": "UNGRACEFUL: ended during the shutdown drain",
    "crashed_during_operation": "UNGRACEFUL: ended without a recorded shutdown",
    "indeterminate_no_record": "NO RECORD: first boot, or no shutdown trail",
}

# Newest boot = highest rowid (insertion order). rowid, not recorded_at: a dead-RTC boot stamps
# a pre-NTP wall clock (data_quality='clock_unsynced') and would mis-order.
_NEWEST_ROW_SQL = (
    "SELECT boot_id, prior_boot_clean, prior_last_entry_ts, "
    "prior_boot_last_stage, prior_boot_reason, recorded_at, data_quality "
    "FROM startup_log ORDER BY rowid DESC LIMIT 1"
)
_COLUMNS = (
    "boot_id", "prior_boot_clean", "prior_last_entry_ts",
    "prior_boot_last_stage", "prior_boot_reason", "recorded_at", "data_quality",
)


@dataclass(frozen=True)
class PriorShutdownSummary:
    """One boot's verdict on the shutdown that preceded it.

    Attributes:
        bootId: The boot that recorded the verdict (the NEXT boot).
        verdict: ``clean`` / ``ungraceful`` / ``no_record``.
        reason: Stored reason code, verbatim (None if the column was NULL).
        lastStage: Highest breadcrumb rung reached, verbatim.
        label: Operator text for the verdict.
        endedAtTs: A recorded end time, or None -- the live value, by design.
        notAfterTs: The next boot's ``recorded_at``: an UPPER BOUND, not an end.
        dataQuality: ``full`` / ``clock_unsynced`` / None, verbatim.
    """

    bootId: str | None
    verdict: str
    reason: str | None
    lastStage: str | None
    label: str
    endedAtTs: str | None
    notAfterTs: str | None
    dataQuality: str | None

    def toStatePayload(self) -> dict[str, Any]:
        """Render for the ``priorShutdown`` block of the system-status file."""
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "lastStage": self.lastStage,
            "label": self.label,
            "endedAtTs": self.endedAtTs,
            "endedAtAbsence": None if self.endedAtTs else END_TIME_ABSENT,
            "notAfterTs": self.notAfterTs,
            "notAfterLabel": NOT_AFTER_LABEL if self.notAfterTs else None,
            "caveat": CAVEAT_UNGRACEFUL if self.verdict == VERDICT_UNGRACEFUL else None,
            "dataQuality": self.dataQuality,
        }


def computePriorShutdownSummary(row: Mapping[str, Any]) -> PriorShutdownSummary:
    """Classify one ``startup_log`` row for display (pure).

    The verdict follows ``prior_boot_clean`` -- the writer's positive-proof
    flag -- and the reason only selects the words.

    Args:
        row: Mapping carrying the ``startup_log`` columns.

    Returns:
        The :class:`PriorShutdownSummary`.
    """
    clean = row.get("prior_boot_clean")
    reason = _asText(row.get("prior_boot_reason"))
    if clean == 1:
        verdict = VERDICT_CLEAN
    elif clean == 0:
        verdict = VERDICT_UNGRACEFUL
    else:
        verdict = VERDICT_NO_RECORD

    label = _REASON_TEXT.get(reason or "")
    if label is None or not label.startswith(_VERDICT_PREFIX[verdict]):
        # Unknown code, or a code that disagrees with the flag: say the flag's
        # verdict and carry the stored code verbatim rather than borrow words.
        label = f"{_VERDICT_PREFIX[verdict]} (reason: {reason or 'none recorded'})"

    return PriorShutdownSummary(
        bootId=_asText(row.get("boot_id")),
        verdict=verdict,
        reason=reason,
        lastStage=_asText(row.get("prior_boot_last_stage")),
        label=label,
        endedAtTs=_asTimestamp(row.get("prior_last_entry_ts")),
        notAfterTs=_asTimestamp(row.get("recorded_at")),
        dataQuality=_asText(row.get("data_quality")),
    )


_VERDICT_PREFIX: dict[str, str] = {
    VERDICT_CLEAN: "CLEAN",
    VERDICT_UNGRACEFUL: "UNGRACEFUL",
    VERDICT_NO_RECORD: "NO RECORD",
}


def formatPriorShutdownLine(summary: PriorShutdownSummary | None) -> str:
    """Render one human line for the operator (CLI / log).

    Args:
        summary: A summary, or None when nothing could be read.

    Returns:
        The line. Never contains an invented end time.
    """
    if summary is None:
        return NOT_READ_LINE
    parts = [f"Previous shutdown: {summary.label}"]
    if summary.verdict != VERDICT_NO_RECORD:
        parts.append(
            f"ended at {summary.endedAtTs}" if summary.endedAtTs else END_TIME_ABSENT
        )
        if summary.notAfterTs:
            parts.append(f"before {summary.notAfterTs} -- {NOT_AFTER_LABEL}")
    if summary.dataQuality == "clock_unsynced":
        parts.append("boot clock unsynced")
    if summary.verdict == VERDICT_UNGRACEFUL:
        parts.append(f"note: {CAVEAT_UNGRACEFUL}")
    return " | ".join(parts)


def readPriorShutdownSummaryFromPath(dbPath: str) -> PriorShutdownSummary | None:
    """Read the newest ``startup_log`` verdict, read-only.

    Best-effort: a missing file, missing table or locked DB returns None --
    "not read", which is a different fact from a NO RECORD row.

    Args:
        dbPath: Path to the Pi SQLite DB.

    Returns:
        The summary, or None when no row could be read.
    """
    if not Path(dbPath).is_file():
        return None
    try:
        # mode=ro: this surface must be physically unable to write the record.
        conn = sqlite3.connect(f"{Path(dbPath).resolve().as_uri()}?mode=ro", uri=True)
        try:
            fetched = conn.execute(_NEWEST_ROW_SQL).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.debug("prior-shutdown read failed (%s) -- not read", exc)
        return None
    if fetched is None:
        return None
    return computePriorShutdownSummary(dict(zip(_COLUMNS, fetched, strict=True)))


def _asText(value: Any) -> str | None:
    """Non-blank string or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _asTimestamp(value: Any) -> str | None:
    """Non-blank, non-epoch-zero timestamp string or None (one absence)."""
    text = _asText(value)
    if text is None or text.startswith("1970-01-01"):
        return None
    return text


def main(argv: list[str] | None = None) -> int:
    """CLI: print the previous-shutdown verdict line.

    Args:
        argv: Optional argument list (defaults to sys.argv when None).

    Returns:
        0 -- an unreadable record is reported, not an error.
    """
    parser = argparse.ArgumentParser(description="Previous-shutdown verdict")
    parser.add_argument("--db", default="data/obd.db")
    args = parser.parse_args(argv)
    print(formatPriorShutdownLine(readPriorShutdownSummaryFromPath(args.db)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
