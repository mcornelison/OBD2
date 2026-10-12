################################################################################
# File Name: drain_calibration.py
# Purpose/Description: ARCH-065a T8 -- turn a 1 Hz powerwatch witness log of a
#                      drain into ONE battery_health_log row: the one-time
#                      `calibration` row for a pack, or the seed `monthly_test`
#                      row (the CIO ruled the 2026-09-27 drain is epoch 3's first
#                      monthly test).  Design: specs/battery-health-design.md
#                      sections 6, 7, 15.8.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a) | Initial.  Every number is imported from its
#               |              | one owner (SSOT): timings from battery_capacity,
#               |              | slope + fill rule from battery_health_finalize,
#               |              | reserve from battery_health_verdict.
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: timestamps use CANONICAL_ISO_FORMAT
#               |              | (src.common.time.helper), not a local literal.
# ================================================================================
################################################################################
"""Drain calibration / seed tool.

    python -m tools.power.drain_calibration --log <witness.log> --date YYYY-MM-DD \
        --mode {monthly_test,calibration} --cell-epoch <epoch> --db <obd.db> [--dry-run]

Nothing here owns a threshold: the window timings, the slope, the window-fill
rule and the reserve are the production code's, imported.  A summary the
finaliser would refuse (window under-filled) is refused here with an error,
never written as a rate.

The database is backed up (sqlite online backup, then ``PRAGMA quick_check`` on
the COPY) before the single INSERT, which runs in a transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.config.validator import CELL_EPOCH_UNKNOWN, CELL_EPOCH_VALUES
from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import (
    DRAIN_TRIGGER_CALIBRATION,
    DRAIN_TRIGGER_MONTHLY_TEST,
)
from src.pi.power.battery_health_finalize import MIN_WINDOW_FILL, windowDrainRate
from src.pi.power.battery_health_verdict import RESERVE_S

__all__ = ['main', 'parseWitnessLog', 'summarise']

_MODES: tuple[str, ...] = (DRAIN_TRIGGER_MONTHLY_TEST, DRAIN_TRIGGER_CALIBRATION)
#: Pack epochs a drain can be attributed to (the 'unknown' sentinel is not one).
_EPOCHS: tuple[str, ...] = tuple(e for e in CELL_EPOCH_VALUES if e != CELL_EPOCH_UNKNOWN)

_LINE = re.compile(
    r"^(\d\d):(\d\d):(\d\d)(\.\d+)?Z seq=\d+ up=([\d.]+) .*?PLD=(\S+) VCELL=([\d.]+)"
)


class WitnessRows(list):  # type: ignore[type-arg]
    """``(seconds_since_first_line, pld, vcell)`` rows plus the first line's wall time.

    A plain list subclass so ``summarise`` also accepts bare lists (then the
    wall-clock fields are None).
    """

    firstWallUtc: datetime | None = None


def parseWitnessLog(path: str, date: str) -> list[tuple[float, str, float]]:
    """Parse a witness log into ``(seconds_since_first_line, pld, vcell)`` rows.

    Seconds come from the ``up=`` field (monotonic, immune to midnight rollover),
    relative to the first data row; the first row's wall clock (``date`` +
    ``HH:MM:SS``) is kept on the returned list as ``firstWallUtc``.  Header and
    unparseable lines are skipped.
    """
    rows = WitnessRows()
    firstUp: float | None = None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            m = _LINE.match(line)
            if not m:
                continue
            up = float(m.group(5))
            if firstUp is None:
                firstUp = up
                frac = float(m.group(4)) if m.group(4) else 0.0
                rows.firstWallUtc = datetime.strptime(
                    f"{date}T{m.group(1)}:{m.group(2)}:{m.group(3)}Z", CANONICAL_ISO_FORMAT,
                ).replace(tzinfo=UTC) + timedelta(seconds=frac)
            rows.append((round(up - firstUp, 3), m.group(6), float(m.group(7))))
    return rows


def _ts(rows: Sequence[tuple[float, str, float]], t: float) -> str | None:
    first = getattr(rows, 'firstWallUtc', None)
    if first is None:
        return None
    return (first + timedelta(seconds=t - rows[0][0])).strftime(CANONICAL_ISO_FORMAT)


def summarise(rows: Sequence[tuple[float, str, float]], mode: str) -> dict[str, Any]:
    """Reduce witness rows to the battery_health_log fields for ``mode``.

    Raises ValueError for a log with no cut, a window the finaliser's fill rule
    would refuse, or (calibration) a drain too short to hold a reserve floor.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
    cutIdx = next(
        (i for i in range(1, len(rows)) if rows[i][1] == "0" and rows[i - 1][1] == "1"), None,
    )
    if cutIdx is None:
        raise ValueError("no cut found: need a PLD=0 row directly after a PLD=1 row")
    cutT = rows[cutIdx][0]
    before = rows[cutIdx - 1]
    afterOne = next((r for r in rows[cutIdx:] if r[0] - cutT >= 1.0), None)
    if afterOne is None:
        raise ValueError("log ends before the cut + 1 s row")
    post = rows[cutIdx:]
    for r in post:
        if r[1] != "0" and r[0] - cutT <= TEST_HOLD_S:
            raise ValueError(
                f"power restored (PLD={r[1]}) {r[0] - cutT:.1f} s after the cut, inside the "
                f"{TEST_HOLD_S} s test window (cut + {TEST_HOLD_S} s); a flap is not a clean test"
            )
    if mode == DRAIN_TRIGGER_CALIBRATION:
        restored = next((r for r in post if r[1] != "0"), None)
        if restored is not None:
            raise ValueError(
                f"calibration log must end on battery: a PLD={restored[1]} row follows the cut "
                f"at +{restored[0] - cutT:.1f} s"
            )
    onBattery = [r for r in post if r[1] == "0"]
    last = onBattery[-1]
    runtime = int(round(last[0] - cutT))

    points = [(r[0] - cutT, r[2]) for r in onBattery
              if WINDOW_SKIP_S <= r[0] - cutT <= TEST_HOLD_S]
    need = MIN_WINDOW_FILL * WINDOW_S
    if len(points) < need or (points and points[-1][0] - points[0][0] < need):
        raise ValueError(
            f"window fill: {len(points)} PLD=0 points over "
            f"{(points[-1][0] - points[0][0]) if points else 0:.0f} s, the finaliser needs "
            f">= {need:.0f} points spanning >= {need:.0f} s -- would be refused, not writing a rate"
        )
    slope = windowDrainRate(points)
    if slope is None:
        raise ValueError("window slope undefined (no distinct times)")
    windowEnd = next((r for r in onBattery if r[0] - cutT >= TEST_HOLD_S), None)
    if windowEnd is None:
        raise ValueError(f"no PLD=0 row at or after cut + {TEST_HOLD_S} s (window end)")
    # end_vcell_v for a monthly_test row is VCELL at the WINDOW END (first row at or
    # after cut + TEST_HOLD_S, as start_vcell_v is the first row at or after cut + 1 s),
    # not the last line of a multi-hour drain: the provisional projection reads
    # end_vcell_v together with window_end_s (battery_health_verdict), so the pair
    # must describe the same instant.
    s: dict[str, Any] = {
        'drain_trigger': mode,
        'start_timestamp': _ts(rows, cutT),
        'end_timestamp': _ts(rows, last[0]),
        'start_vcell_v': afterOne[2],
        'end_vcell_v': windowEnd[2],
        'cut_step_mv': round((before[2] - afterOne[2]) * 1000.0, 3),
        'runtime_seconds': runtime,
        'window_start_s': WINDOW_SKIP_S,
        'window_end_s': TEST_HOLD_S,
        'drain_rate_mv_s': round(slope, 5),
    }
    if mode == DRAIN_TRIGGER_CALIBRATION:
        tFloor = runtime - RESERVE_S
        if tFloor < TEST_HOLD_S:
            raise ValueError(
                f"calibration drain too short: runtime {runtime} s puts the reserve floor at "
                f"{tFloor} s, inside the test window (< {TEST_HOLD_S} s)"
            )
        floorT = last[0] - RESERVE_S
        floorRow = next(r for r in reversed(onBattery) if r[0] <= floorT)
        s['t_floor_s'] = tFloor
        s['floor_vcell_v'] = floorRow[2]
        s['cutoff_vcell_v'] = last[2]
        # A calibration row is the whole drain: close it at the cutoff.
        s['end_vcell_v'] = last[2]
    return s


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _quickCheck(path: str) -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0] == 'ok'
    finally:
        conn.close()


def _backup(db: str) -> str:
    """Copy ``db`` to ``<db>.bak-<UTC>`` and prove the COPY valid; abort if not."""
    dest = f"{db}.bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if not _quickCheck(dest):
        raise RuntimeError(f"backup {dest} failed PRAGMA quick_check; aborting, nothing written")
    return dest


def _insert(db: str, row: dict[str, Any]) -> int:
    cols = list(row)
    sql = (f"INSERT INTO battery_health_log ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)})")
    conn = sqlite3.connect(db)
    try:
        with conn:  # one transaction: commit on success, rollback on error
            conn.execute("BEGIN IMMEDIATE")
            dup = conn.execute(
                "SELECT COUNT(*) FROM battery_health_log WHERE start_timestamp = ? "
                "AND drain_trigger = ? AND cell_epoch = ?",
                (row['start_timestamp'], row['drain_trigger'], row['cell_epoch']),
            ).fetchone()[0]
            if dup:
                raise ValueError(
                    f"duplicate: a battery_health_log row with start_timestamp "
                    f"{row['start_timestamp']}, drain_trigger {row['drain_trigger']}, "
                    f"cell_epoch {row['cell_epoch']} already exists; nothing inserted"
                )
            cur = conn.execute(sql, [row[c] for c in cols])
            return int(cur.lastrowid or 0)
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='drain_calibration', description=__doc__.split('\n')[0])
    ap.add_argument('--log', required=True)
    ap.add_argument('--date', required=True, help='UTC date of the first log line, YYYY-MM-DD')
    ap.add_argument('--mode', required=True, choices=_MODES)
    ap.add_argument('--cell-epoch', required=True, choices=_EPOCHS)
    ap.add_argument('--db', required=True)
    ap.add_argument('--dry-run', action='store_true', help='print the summary JSON; write nothing')
    a = ap.parse_args(argv)

    rows = parseWitnessLog(a.log, a.date)
    try:
        s = summarise(rows, a.mode)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    row: dict[str, Any] = {
        **s,
        'cell_epoch': a.cell_epoch,
        'load_class': 'test',
        'data_source': 'real',
        'close_reason': 'clean',
        'notes': (f"ARCH-065 seed/calibration from {Path(a.log).name}, sha256 {_sha256(a.log)}; "
                  "powerwatch stopped, dashboard NOT shed"),
    }
    if a.dry_run:
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0
    if not Path(a.db).is_file():
        print(f"REFUSED: --db {a.db} does not exist", file=sys.stderr)
        return 2
    backup = _backup(a.db)
    try:
        newId = _insert(a.db, row)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"wrote battery_health_log drain_event_id={newId} ({a.mode}); backup {backup}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
