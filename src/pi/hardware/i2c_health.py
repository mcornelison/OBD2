################################################################################
# File Name: i2c_health.py
# Purpose/Description: ARCH-003 -- durable, process-independent record of I2C
#   transaction health. Exists to turn "the bus might be hiccuping" into
#   evidence, because the bus is read by several independent processes and the
#   suspected failure happens at power loss, when nothing is left to ask.
# Author: Atlas (Architect)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-28    | Atlas   | ARCH-003: instrument first, fix second (CIO-directed)
# ================================================================================
################################################################################

"""Durable I2C transaction-health record.

**Why a file and not a counter.** ``drain-forensics`` is a systemd timer with
``OnUnitActiveSec=5s``: a brand-new process opens the bus every five seconds and
exits about a second later. Anything held in memory dies with it. The record has
to outlive the process that wrote it, because the event we are hunting -- a bus
hiccup starving the UPS read at power loss -- is followed immediately by the
machine going away.

**Why a monotonic reading and a clock-trust flag.** This Pi's RTC
trickle-charger was never enabled (A-23), so the wall clock in the car is
whatever it last synced to over WiFi. A record carrying only wall time would be
another confident-but-wrong artefact, which is the defect class this project
keeps tripping over. So every row carries:

* ``monotonic`` -- ordering that is correct even when the clock is nonsense,
* ``clockSynced`` -- an explicit statement of whether the wall time can be
  trusted, rather than leaving the reader to guess.

That is ``specs/ssot-design-pattern.md``'s honest-availability rule applied to
our own instrument: an unavailable fact is declared, never fabricated.

**Why it swallows its own errors.** An instrument that can take down the thing
it measures is worse than no instrument. Every write is best-effort; a failure
to record is never allowed to fail a bus read.

Deliberately NOT included: rotation, locking, or a background flusher. Rows are
small and appended with a single ``write`` call in append mode, which is atomic
enough for this purpose on Linux for the sizes involved. Adding machinery here
would be adding failure modes to a diagnostic.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the record lives by default. Under ``/var/log`` rather than ``/run`` on
#: purpose: ``/run`` is tmpfs and would be erased by the very power loss this
#: record exists to explain.
DEFAULT_HEALTH_PATH = Path("/var/log/eclipse-obd/i2c-health.jsonl")

#: Cap on how much we will read back, so a pathological file cannot balloon a
#: caller's memory. Newest rows are the interesting ones, but callers read the
#: whole file today; keep this generous and revisit only with evidence.
MAX_ROWS_READ = 50_000


class I2cEvent(StrEnum):
    """What happened to one I2C transaction.

    ``RETRIED`` and ``RECOVERED`` are the early-warning pair: a bus that is
    degrading but still returning answers. Those are the rows that would tell us
    contention is building BEFORE it swallows a UPS read -- which a
    failures-only record would never show.

    ``DEVICE_MISSING`` is kept distinct from ``FAILED`` deliberately. ENODEV
    means nothing is at that address; that is an absent sensor, not the bus
    misbehaving, and conflating the two would make an unplugged device look
    exactly like the contention we are hunting.
    """

    RETRIED = "retried"
    RECOVERED = "recovered"
    FAILED = "failed"
    DEVICE_MISSING = "device_missing"


def _defaultClockSynced() -> bool:
    """Best-effort read of whether the system clock has been disciplined.

    Returns False when it cannot tell. Guessing "True" here would defeat the
    entire point of the flag -- an unknown clock is not a trusted clock.
    """
    try:
        # systemd-timesyncd drops this file once it has stepped the clock.
        return Path("/run/systemd/timesync/synchronized").exists()
    except Exception:  # noqa: BLE001 -- a probe must never raise
        return False


class I2cHealthRecorder:
    """Append-only, process-independent record of I2C transaction outcomes."""

    def __init__(
        self,
        path: Path | str = DEFAULT_HEALTH_PATH,
        clockSyncedFn: Callable[[], bool] | None = None,
    ) -> None:
        """Args:
            path: JSONL file to append to. Parent dirs are created if missing.
            clockSyncedFn: Injectable clock-trust probe (tests supply their own).
        """
        self._path = Path(path)
        self._clockSyncedFn = clockSyncedFn or _defaultClockSynced

    def record(
        self,
        event: I2cEvent,
        *,
        address: int,
        register: int | None = None,
        operation: str = "",
        attempts: int = 1,
        errno: int | None = None,
        **extra: Any,
    ) -> None:
        """Append one outcome. NEVER raises -- see the module docstring."""
        try:
            row = {
                "event": I2cEvent(event).value,
                "monotonic": time.monotonic(),
                "wallTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "clockSynced": bool(self._clockSyncedFn()),
                "address": f"0x{address:02x}",
                "register": None if register is None else f"0x{register:02x}",
                "operation": operation,
                "attempts": attempts,
                "errno": errno,
                "pid": os.getpid(),
            }
            row.update(extra)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            logger.debug("i2c health record dropped: %s", exc)

    def readAll(self) -> list[dict[str, Any]]:
        """Return every well-formed row. A missing file yields ``[]``.

        Malformed lines are SKIPPED, not fatal: a truncated final line is the
        expected shape of a file that was being appended to when the power went
        out -- which is precisely the case this record is for.
        """
        rows: list[dict[str, Any]] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
                    if len(rows) >= MAX_ROWS_READ:
                        break
        except (OSError, UnicodeDecodeError):
            return rows
        return rows


__all__ = ["I2cEvent", "I2cHealthRecorder", "DEFAULT_HEALTH_PATH"]
