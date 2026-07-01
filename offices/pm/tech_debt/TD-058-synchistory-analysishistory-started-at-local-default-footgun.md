# TD-058: sync_history / analysis_history `started_at` DB default is server-LOCAL time (`func.now()`) — the F-079 5h footgun survives at the schema layer

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code / testing            |
| Affected     | `src/server/db/models.py` (`SyncHistory.started_at` ~L800, `AnalysisHistory.started_at` ~L820); the DB column DEFAULT on `sync_history.started_at` / `analysis_history.started_at` in MariaDB |
| Introduced   | US-333 (2026-05-12) fixed the B-079 5h mismatch at the *writer* only; the model `server_default=func.now()` was left as-is |
| Created      | 2026-07-01 (surfaced while closing US-414 / F-079) |

## Description

`SyncHistory.started_at` and `AnalysisHistory.started_at` both declare
`DateTime, nullable=False, server_default=func.now()`. On MariaDB, `func.now()`
maps to `CURRENT_TIMESTAMP`, which returns the **server's local time** (America/
Chicago, CDT/CST) — **not UTC**. Every other timestamp in the pipeline is written
in UTC (`datetime.now(UTC)`), per `specs/standards.md`.

Today there is **no live bug**: US-333 made `_createSyncHistoryRow` set
`started_at` explicitly from `datetime.now(UTC)`, so the local-time
`server_default` is never actually exercised on the sync path (the analysis path
similarly sets `started_at=startedAt` in `services/analysis.py`). The footgun is
**latent**: any *future* code path (or a raw `INSERT`, backfill, or ORM insert
that forgets to set `started_at`) falls back to the local-time default and
silently reintroduces the exact F-079 / B-079 5h intra-row mismatch
(`completed_at` in UTC vs `started_at` in CDT → the ~18000s artifact).

## Why It Was Accepted

US-414 (F-079) is scoped to "the sync_history **writer** writes both columns in
UTC" — which US-333 already satisfied and US-414 completed the regression
coverage for (create/complete/**fail** paths all pinned). Changing the *column
default* is a schema change: it needs a MariaDB migration (`ALTER TABLE ... ALTER
COLUMN started_at SET DEFAULT ...`) and there is **no clean portable UTC default**
(`func.now()`/`CURRENT_TIMESTAMP` is local on MariaDB; a UTC default needs
`UTC_TIMESTAMP()` or dropping the default and mandating the writer). It is also
**not reproducible on the dev box** — SQLite's `CURRENT_TIMESTAMP` is already UTC,
so the footgun cannot be red-tested locally without MariaDB. That is out of
scope for an XS sync-drain story and warrants a design decision.

## Risk If Not Addressed

- **Likelihood:** Low — every current writer sets `started_at` explicitly.
- **Impact:** Low-Medium — a future writer/backfill silently regresses F-079 on
  new rows only; duration metrics (`completed_at - started_at`) become the ~5h
  artifact again and the regression is invisible until someone re-queries the
  duration. `analysis_history` carries the same shape and is the more likely
  future re-writer (AI analysis runs).

## Remediation Plan

Pick one, PM/Atlas to rule (SSOT-design gate, since it's a schema convention):

1. **Drop the local-time default and mandate the writer** (matches the current
   SSOT-provider pattern): remove `server_default=func.now()` from both
   `started_at` columns; keep `nullable=False`; rely on the writer's explicit
   UTC stamp (already in place). Migration = `ALTER COLUMN ... DROP DEFAULT`.
2. **Make the default UTC**: `server_default=text("UTC_TIMESTAMP()")` (MariaDB) —
   keeps a belt-and-braces default but portable/testing story is muddier.

Add a MariaDB-gated (or documented deferred) regression asserting a default-only
insert lands within seconds of a UTC `completed_at`. Track against E-OPS
alongside F-079.
