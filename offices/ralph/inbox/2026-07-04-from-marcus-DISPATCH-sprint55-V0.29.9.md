from=Marcus(PM); to=Rex(Dev); date=2026-07-04; topic=DISPATCH Sprint 55/V0.29.9 -- F-104 Server-Side Analytics Authority spine (bench-only, 10 stories, HIGH-RISK identity re-architecture); audience=agent; urgency=high; refs=US-448,US-449,US-450,US-451,US-452,US-453,US-454,US-455,US-456,US-457

# Marcus -> Rex: Sprint 55 / V0.29.9 DISPATCHED

Branch **`sprint/sprint55-V0.29.9`** forked from `dev`, pushed, upstream set. **10 stories. This is the highest-risk sprint of the chain -- it re-architects DRIVE IDENTITY.** Atlas-approved; his F-104 ADR is BINDING.

## Binding design authority (do NOT deviate)
`offices/architect/reports/2026-07-04-f104-server-analytics-authority-design-gate-ruling.md` (+ the `[ATLAS]` blocks in `offices/pm/prds/prd-V0.29.9.md`). **The boundary rule:** server-authoritative iff reproducible from synced raw -> server sole-writer, Pi does NOT transmit; else it's raw -> Pi emits as raw. No "derived state the Pi transmits."

## Testing + migrations
Targeted tests SYNCHRONOUS + commit in-iteration (TD-059). **`ruff` in-loop; `mypy` is PM-integration (not in your env)** -- don't block on mypy. **Every migration forward-only + deployed-AND-verified via INFORMATION_SCHEMA.**

## The SPINE -- strict chain, do in order
1. **US-448 canonical `drives` + server `drive_id` (L, PM-signed-off) -- MIGRATION-FIRST, start here.** ⚠️ **SUBSUME the existing `drive_summary.id`** (the de-facto identity `drive_statistics` already FKs to) -- migrate it IN as `drive_id`; do NOT mint a 5th orthogonal id. **Mint = autoincrement anchored by `UNIQUE(source_device, source_drive_id)` + UPSERT-by-natural-key** (idempotent recompute re-uses the id, NEVER renumbers -- straight autoincrement is forbidden). ⚠️ **The `detect_overlapping_drives` tripwire MUST keep DETECTING on the raw `realtime_data.drive_id`** (the Pi-dual-mint signal, overlap.py:87-93) -- "re-point" only maps its OUTPUT to the canonical identity; do NOT regroup it by server drive_id (blinds the backstop). Re-point the output BEFORE any `connection_log` rename. Fixture asserts it still trips on a raw dual-mint pair.
2. **US-449 formalize the harness (M; deps 448)** -- ⚠️ **the harness EXISTS** (`drive_summary_compute.py`/`drive_statistics_compute.py`/`derived_signals_compute.py` + `server-analytics-batch.timer`). **FORMALIZE, do NOT build**: owned-table manifest + prove idempotency (re-run = 0 diffs) + re-key to canonical `drive_id`.
3. **US-450 drive_statistics re-key + empty-table gap (M; deps 449)** -- compute EXISTS + Pi-side retired. Re-key to canonical id; **reconcile the row-count gap** (Atlas saw 0 on chi-srv-01, Spool saw 434 -- likely a deploy/timer gap; fix or flag QA with evidence, do NOT rebuild the compute). F-116 excludes foreign.
4. **US-451 collapse id-families -> one `drive_id` (L, PM-signed-off; deps 448)** -- Pi ids -> advisory `source_*`; back-map existing; **UNMAPPABLE legacy (drives 1-12, foreign 33, NULL-id) -> flag `data_quality='unmappable_legacy'`, one row per key, NEVER drop/merge.**

## Independent D-items
5. **US-452** D-1 statistics-vs-drive_statistics no-dual-write (deps 450). 6. **US-453** D-7 raw-sync power_log+pi_state. 7. **US-454** D-3 O2 name canonicalize (+ US-229 fixture lockstep). 8. **US-455** D-4 unit-string canonicalize (`volt` not `V`; unit=label never numeric). 9. **US-456** D-5 static_data drop+TD-061 (or honest-empty; CIO -- VIN Mode-09-silent).

## Last
10. **US-457 doc-sync** -- architecture.md server-authority section + ssot worked example. **US-448 + US-449 do NOT close until this lands (Rule-10, A-11).**

## Validation = BENCH ONLY
DB introspection + INFORMATION_SCHEMA + idempotency re-runs (0 diffs) + tripwire fixture + compute-vs-raw equivalence. NO drive drills. (F-083 + the analysis/AI tier are Sprint 56.)

## Notes
- If you hit ambiguity on a spine story, STOP and flag me/Atlas (Refusal Rule 1) -- this is identity-migration, a wrong guess is expensive. Commit to THIS branch; stale index.lock = TD-057.

CIO launches `ralph.sh` from his shell.

-- Marcus
