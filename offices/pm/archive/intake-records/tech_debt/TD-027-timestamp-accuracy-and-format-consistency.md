# TD-027: Timestamp accuracy + format consistency across Pi log tables

| Field        | Value                                                 |
|--------------|-------------------------------------------------------|
| Severity     | High (corrupts post-drill data-window analysis; contaminates Spool tuning-review conclusions) |
| Status       | **Fully Closed (US-202 + US-203, 2026-04-19)** — all 12 capture-table writers (4 in US-202 + 8 in US-203) routed through `src/common/time/helper.utcIsoNow`; schema DEFAULTs updated; helper + tests in place; specs/standards.md updated; Thread 1 findings documented below. Capture tables (`connection_log`, `alert_log`, `battery_log`, `power_log`, `realtime_data`, `statistics`) now produce ONLY canonical ISO-8601 UTC format on all new inserts. |
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

## Thread 1 Investigation — findings (US-202, 2026-04-19)

Ralph ran the requested query against Pi `data/obd.db` (chi-eclipse-01,
`/home/mcornelison/Projects/Eclipse-01/data/obd.db`) at US-202 execution
time. Raw output (Session 23 drill window, `connection_log` ordered by id):

```
id|event_type|timestamp|success
 1|connect_attempt|2026-04-19 12:17:09|0
 2|connect_attempt|2026-04-19 12:17:10|0
 3|connect_attempt|2026-04-19 12:17:12|0
 4|connect_attempt|2026-04-19 12:17:16|0
 5|connect_attempt|2026-04-19 12:17:24|0
 6|connect_attempt|2026-04-19 12:17:40|0
 7|connect_failure|2026-04-19 12:17:40|0
 8|disconnect|2026-04-19 12:17:40|0
 9|connect_attempt|2026-04-19 12:18:10|0
10|connect_success|2026-04-19 12:18:50|1
11|disconnect|2026-04-19 12:18:51|0
12|connect_attempt|2026-04-19 12:19:41|0
13|connect_success|2026-04-19 12:20:19|1
14|drive_start|2026-04-19 07:20:30.837646|1   ← FORMAT DRIFT
15|drive_end  |2026-04-19 07:20:41.427040|1   ← FORMAT DRIFT
16|disconnect |2026-04-19 12:20:41|0
```

**True connection-activity span**: rows 1..16 span 12:17:09 UTC to
12:20:41 UTC = **~3.5 minutes (212 seconds)** — matching CIO's recollection
of "several minutes", NOT Spool's 23-second figure.

**Format drift observed**: rows 14 and 15 (`drive_start` / `drive_end`,
written from `src/pi/obdii/drive/detector.py:616` via naive
`datetime.now()`) show hour `07:xx` with microseconds. Every other row
(from `src/pi/obdii/obd_connection.py:445` via `DEFAULT CURRENT_TIMESTAMP`,
which is UTC) shows hour `12:xx` without microseconds. The offset is
exactly **5 hours**, matching America/Chicago CDT (UTC-5) in April with
DST. This is the naive-local-time bug from Thread 2 of this TD, and it is
the direct cause of lexicographic `BETWEEN` / `MAX-MIN` queries returning
wrong spans.

**Diagnosis**: the 23-second discrepancy is **both**:

- **(b) format-mix-corrupts-delta** — if the 23s figure came from a delta
  that mixed row 14 or 15 (07:xx local) with row 16 (12:xx UTC), the
  lexicographic compare returns an apparent ~10.5s window between rows
  14–15 alone, or a negative/bogus delta when mixed with 12:xx strings.
  Exact shape of the 23s calculation is unknown without Spool's query
  text, but the format drift is sufficient cause.
- **(a) gap-between-events** (structural, separate concern) — even with
  correct format, `connection_log` only writes on OPEN / CLOSE / retry
  events. The ~30s gaps between row 11 (disconnect 12:18:51) and row 12
  (attempt 12:19:41), and between row 13 (success 12:20:19) and row 16
  (disconnect 12:20:41), represent continuous activity not recorded by
  intermediate rows. `MAX - MIN` over this table is a proxy for
  wall-clock span — imperfect by design.

**Resolution for US-202**: Thread 2 (the format drift) is fixed by this
story. Thread 1's gap-between-events is **out of scope** per Invariant #4
("Do NOT couple this fix to TD-027 Thread 1's heartbeat-logging
proposal"). Filed Sprint 15+ follow-up in PM inbox note alongside US-202
closure: consider heartbeat rows (`event_type='HEARTBEAT'` every N
seconds while connected) or session-end fields on the OPEN row if
tuning-review-grade wall-clock span reconstruction becomes a requirement.
Not urgent — the new canonical format + `realtime_data` row density
already give a trustworthy wall-clock reconstruction for drill analysis.

## Fix completion note (US-202, 2026-04-19)

**In scope of US-202 (completed)**:

- New module: `src/common/time/helper.py` with `utcIsoNow()` and
  `toCanonicalIso(dt)` — the latter rejects naive datetimes at the
  boundary.
- `CANONICAL_ISO_FORMAT` and `CANONICAL_ISO_REGEX` exported for use by
  tests and future callers.
- Schema DEFAULTs changed on 6 tables (`connection_log`, `alert_log`,
  `battery_log`, `power_log` from `DEFAULT CURRENT_TIMESTAMP`; added
  `DEFAULT (strftime(...))` on `realtime_data.timestamp` and
  `statistics.analysis_date` which previously had none).
- 4 explicit writers named in the TD spec routed through the helper:
  `sync_log.py`, `switcher.py`, `data_retention.py`, `drive/detector.py`.
  `obd_connection.py:445` verified as using the DEFAULT path (no Python
  change needed).
- Tests: `tests/common/time/test_helper.py` (10/10 green),
  `tests/pi/data/test_timestamp_format.py` (9/9 green) — regex assertions
  on DEFAULT path, DEFAULT vs explicit shape parity, tz-naive rejection,
  schema idempotency.
- `specs/standards.md` Section 13 grew a "Canonical Timestamp Format"
  subsection documenting the rule + helper + schema pattern.
- No historical rows backfilled (per Invariant #1). Session 23 mixed
  formats remain intact for forensic audit value.

**Out of scope, flagged to PM**:

- 8 additional explicit-timestamp writers across the Pi tree not named
  in the TD spec (stopCondition #4 triggered). Audited; findings filed
  in `offices/pm/inbox/2026-04-19-from-ralph-us202-additional-writers.md`
  for Sprint 15+ decision on whether to expand the sweep.

**Verification evidence**: see US-202 closure in `offices/ralph/sprint.json`
and progress.txt for commands + test output.

## Fix completion note (US-203, 2026-04-19)

US-203 completed the TD-027 sweep. The 8 additional writers flagged by
US-202's stopCondition #4 (inbox note
`2026-04-19-from-ralph-us202-additional-writers.md`) all now route their
capture-table INSERTs through `src/common/time/helper.utcIsoNow`.

### Final writer audit table (all 12 capture-table writers across US-202 + US-203)

| # | File:line (pre-fix) | Table | Fix story | Pattern |
|---|---------------------|-------|-----------|---------|
| 1 | `src/pi/data/sync_log.py:136` | sync_log helper | US-202 | inline `datetime.now(UTC).strftime(...)` -> `utcIsoNow()` |
| 2 | `src/pi/profile/switcher.py:607` | calibration_sessions | US-202 | `event.timestamp` (naive) -> `utcIsoNow()` |
| 3 | `src/pi/obdii/data_retention.py:457` | connection_log | US-202 | `datetime.now()` -> `utcIsoNow()` |
| 4 | `src/pi/obdii/drive/detector.py:616` | connection_log | US-202 | `timestamp` param (naive caller) -> `utcIsoNow()` |
| 5 | `src/pi/obdii/obd_connection.py:445` | connection_log | US-202 (no code change) | uses DEFAULT path; canonical via schema DEFAULT |
| 6 | `src/pi/power/power_db.py:60` (`logPowerReading`) | power_log | US-203 | `reading.timestamp` (naive) -> `utcIsoNow()` |
| 7 | `src/pi/power/power_db.py:99` (`logPowerTransition`) | power_log | US-203 | `timestamp` param (naive caller) -> `utcIsoNow()` at boundary; param kept for BC |
| 8 | `src/pi/power/power_db.py:136` (`logPowerSavingEvent`) | power_log | US-203 | `datetime.now()` -> `utcIsoNow()` |
| 9 | `src/pi/obdii/data/logger.py:202` (`ObdDataLogger.logReading`) | realtime_data | US-203 | `reading.timestamp` (naive, from `realtime.py:399` or `queryParameter:148`) -> `utcIsoNow()` at boundary |
| 10 | `src/pi/obdii/data/helpers.py:100` (`logReading`) | realtime_data | US-203 | `reading.timestamp` (naive) -> `utcIsoNow()` at boundary |
| 11 | `src/pi/analysis/engine.py:264,681` (`_storeStatistics`) | statistics | US-203 | line 264 `datetime.now()` -> `datetime.now(UTC)`; INSERT uses `toCanonicalIso(stats.analysisDate)` so all rows in one analysis share the same canonical date |
| 12 | `src/pi/alert/manager.py:494` (`_logAlertToDatabase`) | alert_log | US-203 | `event.timestamp` (naive, from `AlertEvent.__post_init__`) -> `utcIsoNow()` at boundary |
| 13 | `src/pi/power/battery.py:551` (`BatteryMonitor._logToDatabase`) | battery_log | US-203 | `reading.timestamp` (naive, from `VoltageReading.__post_init__`) -> `utcIsoNow()` at boundary |

(13 entries; writer #5 did not require a code change, so 12 code-touched writers across US-202 + US-203.)

### Upstream dataclasses left as-is (per Invariant #4)

The naive `datetime.now()` calls inside `AlertEvent.__post_init__`
(`src/pi/alert/types.py:167`), `PowerReading.__post_init__`
(`src/pi/power/types.py:159`), `VoltageReading.__post_init__`
(`src/pi/power/types.py:241`), and `queryParameter`
(`src/pi/obdii/data/logger.py:148`) were NOT modified.  These remain naive
so in-memory behavior is preserved; the TD-027 invariant only applies at
the DB-write boundary.  Coercing-at-boundary matches the US-202 precedent
from `drive/detector.py:616` and avoids a broader dataclass refactor
(explicit invariant #4 on US-203).

### Tests added in US-203

- `TestExplicitPathWriters` (8 tests) -- each writer's INSERT verified to
  produce canonical ISO-8601 UTC by running it against an in-memory Pi
  schema DB and asserting `CANONICAL_ISO_REGEX` match.
- `TestNoDatetimeNowInCaptureWriteFunctions` (8 tests) -- AST-walk each
  capture-write function's source; fail if any `datetime.now()` Call node
  with zero args appears (comments + docstrings are correctly ignored
  because AST does not parse string literals for Call nodes).
- Fast suite: 2244 baseline (post-US-195) -> 2260 (+16 new tests, 0
  regressions).

### Ambiguous writers resolved (from US-202 inbox note)

All 3 ambiguous writers resolved as part of US-203:

- `power_db.py:60` (`logPowerReading` -- reading.timestamp): coerced at
  DB boundary.
- `power_db.py:94` (`logPowerTransition` -- timestamp param): coerced at
  DB boundary; param retained for BC (unused, noqa'd).
- `battery.py:551` (`_logToDatabase` -- reading.timestamp): coerced at
  DB boundary.

No unexpected fourth writer surfaced (stopCondition #3 of US-203 did not
trigger).  TD-027 is now fully closed.
