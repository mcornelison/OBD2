# TD-027: Timestamp accuracy + format consistency across Pi log tables

| Field        | Value                                                 |
|--------------|-------------------------------------------------------|
| Severity     | High (corrupts post-drill data-window analysis; contaminates Spool tuning-review conclusions) |
| Status       | Open                                                  |
| Filed By     | Ralph (at CIO direction), Session 24, 2026-04-19      |
| Surfaced In  | Spool review of Session 23 milestone drill — claimed "~23 seconds across 2 connection windows" when CIO states actual elapsed collection time was **several minutes**, not 23s |
| Blocking     | Any tuning-review-grade conclusion drawn from Session 23 data; any future drill's window-of-capture reporting; CR #4 `data_source` column design (needs trustworthy timestamps to make sense) |

## Problem (two threads, probably related)

### Thread 1 — Computed elapsed time is wrong

Spool's post-drill review (`offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`) reported a ~23 second real-data window based on `connection_log` rows. CIO disputes this directly: the drill ran for **several minutes**, not 23 seconds. Engine was idling for the full span. The `realtime_data` row count (149 rows in ~60s of collector runtime) is consistent with minutes of polling, not seconds.

Possible causes to investigate:
- `connection_log` only writes on state transitions (OPEN / CLOSE / retry), so `MAX(timestamp) - MIN(timestamp)` per session gives the gap between the first and last *events*, not the true wall-clock span the collector was running. If the collector briefly disconnected mid-drill and reconnected, the two "windows" are session segments, and the gap between them is NOT counted.
- Or — the collector was actually connected continuously but the log writer was suppressing "idle" / "still alive" heartbeat events, so only the first OPEN and last CLOSE landed in the table, compressing the span.
- Or — timestamps on some rows are being written with naive local time (see Thread 2), and when compared against UTC rows the arithmetic produces a bogus delta.

### Thread 2 — Format / tz inconsistency in write paths

Three distinct timestamp-writing patterns exist in the Pi code for `connection_log` alone (same likely applies to `alert_log`, `battery_log`, `power_log`, `realtime_data`):

1. **SQLite `DEFAULT CURRENT_TIMESTAMP`** — used by `src/pi/obdii/obd_connection.py:445-447` and others that omit `timestamp` from the INSERT column list. SQLite's `CURRENT_TIMESTAMP` returns **UTC** in format `YYYY-MM-DD HH:MM:SS` (space separator, no `T`, no `Z`).
2. **Python-generated, explicit in INSERT** — used by `src/pi/profile/switcher.py:607`, `src/pi/obdii/data_retention.py:457`, `src/pi/obdii/drive/detector.py:616`. Need to verify what value each caller actually passes (spot check: is it `datetime.now()` [naive local — WRONG on Pi which is in America/Chicago], or `datetime.now(UTC).strftime(...)` [correct UTC]?).
3. **`src/pi/data/sync_log.py:136`** pattern — uses `datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')` (ISO-8601 with `T` separator and trailing `Z`). The docstring on line 132-134 claims this matches `connection_log` format, but the `DEFAULT CURRENT_TIMESTAMP` path (pattern 1) does NOT produce a `T` or `Z` — so the docstring is wrong or the two formats coexist in the same table.

Result: a single `connection_log` query can return rows in TWO different string formats depending on which code path inserted them. Downstream tools that parse or compare these strings lexicographically will produce inconsistent answers.

## Expected behavior

- **Every timestamp in every capture table is UTC**, with explicit timezone awareness — never a naive `datetime.now()`.
- **Format is uniform across all writers** — recommend ISO-8601 UTC with `T` and trailing `Z` (`YYYY-MM-DDTHH:MM:SSZ`) since that's what `sync_log.py` already documents as canonical.
- `connection_log` captures enough events to reconstruct a real session duration. If today it only logs on OPEN/CLOSE, and the collector ran for several minutes between those events, either (a) add periodic heartbeat rows (`event_type='HEARTBEAT'`) so wall-clock can be reconstructed from row density, or (b) add `session_end_timestamp` + `session_duration_seconds` fields to the OPEN row on close.
- All existing analysis + reporting code that computes time deltas understands the format and tz uniformly.

## Proper fix (investigation + code)

1. **Audit** every `INSERT` that writes a `timestamp` column across the Pi tree (grep `INSERT INTO .*log` and `INSERT INTO realtime_data`). Document which uses `CURRENT_TIMESTAMP` default, which uses Python explicit, and what tz semantics each explicit one actually has. Deliverable: a short audit table in the TD or an inline comment in `database_schema.py`.
2. **Unify** to ISO-8601 UTC with `T` and `Z`. Options:
   - Replace `DEFAULT CURRENT_TIMESTAMP` with `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))` at the schema level (SQLite supports this and produces the canonical format).
   - And/or: require all explicit-timestamp INSERTs go through a single `_utcNow()` helper (extract from `sync_log.py:136` into a shared `src/common/time/` module — reusable across Pi + server).
3. **Investigate the 23-second discrepancy**: run a query on the Session 23 `obd.db` (before it's overwritten) and see what `connection_log` actually contains — event_types, timestamps, row count. If gaps between events are the cause, file a follow-up to add heartbeat logging. If the tz/format mix caused the delta computation to be wrong, this unification step fixes it directly.
4. **Spec the canonical format** in `specs/architecture.md` or `specs/standards.md` so future code reviews catch drift.

## Acceptance for fix

- Running `SELECT DISTINCT substr(timestamp, 11, 1) FROM connection_log` returns only `'T'` (no space-separator rows) — unified format.
- `SELECT timestamp FROM connection_log ORDER BY timestamp LIMIT 1` returns a string ending in `Z`.
- New audit table (committed as a comment or short doc) lists every `timestamp` writer in the Pi tree and confirms each produces UTC + canonical format.
- For Session 23 `obd.db` specifically: when the regression fixture is exported to `data/regression/pi-inputs/eclipse_idle.db` (US-168 AC #7), it should either be re-stamped with a short note about the format mix OR explicitly documented as "pre-TD-027 — do not use for timestamp-delta analysis".
- Mocked test in `tests/pi/data/` covers: (a) naive `datetime.now()` rejected / guarded by the helper, (b) stored format matches regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`, (c) `DEFAULT` and explicit paths produce the same string shape for a fixed moment.

## Related

- TD-025 / TD-026 (SyncClient assumptions about PKs) — not directly coupled, but any server-side timestamp comparison across Pi pushes will benefit from format uniformity
- CR #4 `data_source` column (Spool spec, Sprint 14 candidate) — can't confidently tag / filter by time window until this is resolved
- US-168 carryforward AC #7: `data/regression/pi-inputs/eclipse_idle.db` fixture export — should be done BEFORE any timestamp-rewriting migration runs, so the historical snapshot preserves exactly what was captured
- `src/pi/data/sync_log.py:132-136` — current canonical helper; lift to `src/common/` as part of the fix
