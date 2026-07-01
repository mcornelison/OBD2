from=Rex(Dev); to=Marcus(PM); date=2026-07-01T00:00:00Z; topic=US-414/F-079 done; already-fixed-by-US-333 + TD-058 footgun; audience=agent; refs=US-414,F-079,US-333,B-079,TD-058

US-414 DONE (passes:true, committed). Heads-up on provenance + a filed follow-up.

FINDING: F-079 == B-079 (renamed 2026-05-27, backlog still status:pending). The 5h intra-row
`sync_history` mismatch it reports was ALREADY FIXED by US-333 (2026-05-12) —
`_createSyncHistoryRow` stamps `started_at` from `datetime.now(UTC)`, `_completeSyncHistoryRow`/
`postSync` + `_failSyncHistoryRow` stamp `completed_at` from the same UTC clock. The regression
test `tests/server/test_sync_history_timestamps_utc.py` (US-333) already pins create+complete
consistency and RUNS GREEN today (verified). So all three US-414 ACs were met by existing code+test
before I started.

WHAT I DID (genuine in-scope delta): the FAIL path (`_failSyncHistoryRow`, which also stamps
`completed_at`) had NO regression pin — a future revert to DB-local `func.now()` on that path would
silently reintroduce the 5h mismatch on error rows, uncaught. Added
`test_failSyncHistoryRow_stampsCompletedAtFromUtcClock` so all three writer paths
(create/complete/fail) are now held to UTC. 3 tests green; server slice 128 passed; ruff clean.
No production code change (none needed — the fix already exists).

FILED TD-058: `SyncHistory.started_at` + `AnalysisHistory.started_at` still carry
`server_default=func.now()` = MariaDB SERVER-LOCAL time (not UTC). NO live bug (every writer sets
started_at explicitly), but it's a latent footgun: any future writer/backfill that omits started_at
falls back to CDT and F-079 returns on new rows. Fixing the column default is a MariaDB migration +
a schema-convention (SSOT) decision + not red-testable on the dev box (SQLite CURRENT_TIMESTAMP is
already UTC) → out of scope for an XS drain story. Recommend an E-OPS follow-up; PM/Atlas to rule
(drop-default-and-mandate-writer vs UTC_TIMESTAMP default).

SUGGEST: mark F-079 backlog resolved (credit US-333 fix + US-414 coverage completion).

Sprint 50 remainder: US-415 (doc-sync, S) unclaimed/unblocked; US-412 BLOCKED (BL-013, power_log half
committed). Single-agent → no promise tag; ralph.sh continues to US-415.
