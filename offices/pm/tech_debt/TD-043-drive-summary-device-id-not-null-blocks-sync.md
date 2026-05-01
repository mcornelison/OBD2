# TD-043: drive_summary.device_id NOT NULL with no default blocks Pi sync (post-Sprint-20 deploy bug)

| Field | Value |
|---|---|
| Filed by | Marcus (PM), 2026-05-01 post-Sprint-20 deploy verification |
| Severity | P0 -- drive_summary sync still failing 500 in production |
| Resolution | RESOLVED 2026-05-01 via live sudo ALTER (CIO ran). drive_summary sync_log status flipped failed -> ok with last_synced_id=5 (4 previously-orphaned rows synced + 1 new). |
| Category | server / migration / schema |
| Affected | `src/server/migrations/versions/v0004_us237_drive_summary_reconcile.py`, server `drive_summary` table |
| Surfaced In | post-Sprint-20 deploy 2026-05-01 (commits `99e3e5b` server + `99e3e5b` Pi); journal shows continuous 500s on `/api/v1/sync` for `drive_summary` |
| Filed | 2026-05-01 |

## Resolution (2026-05-01)

Two legacy NOT-NULL columns surfaced sequentially during post-Sprint-20 deploy verification:

1. `device_id` (first 500-error blocker) -- CIO ran `ALTER TABLE drive_summary MODIFY device_id VARCHAR(64) NULL DEFAULT NULL;`
2. `start_time` (next blocker after device_id fixed) -- CIO ran `ALTER TABLE drive_summary MODIFY start_time DATETIME NULL DEFAULT NULL;`

After both ALTERs, Pi sync_log flipped `drive_summary | 0 | failed` -> `drive_summary | 5 | ok`. The 4 previously-orphaned Pi rows (drive_ids 2-5) synced + 1 new row.

**Sprint 21 follow-up still required**: write the proper migration (v0007 or equivalent) that captures these ALTERs in version control + audit remaining legacy columns (`end_time`, `duration_seconds`, `profile_id`, `row_count`) for similar NOT-NULL-without-default issues that may surface on future drive shapes. Live ALTERs aren't reproducible across server reinstalls.

## Symptom

After Sprint 20 deploy, server log shows continuous 500s on every Pi `drive_summary` sync attempt:

```
ERROR | src.server.api.sync | Sync upsert failed for batch chi-eclipse-01-2026-05-01T10:31:05Z:
  (pymysql.err.OperationalError) (1364, "Field 'device_id' doesn't have a default value")

[SQL: INSERT INTO drive_summary (row_count, data_source, source_id, source_device, synced_at,
      sync_batch_id, drive_start_timestamp, ambient_temp_at_start_c, starting_battery_v,
      barometric_kpa_at_start) VALUES (...)
      ON DUPLICATE KEY UPDATE ...]
```

Pi `sync_log.drive_summary` remains `last_synced_id=0 status=failed`. Same outcome as the pre-Sprint-19 TD-038 symptom -- the v0004 migration was supposed to fix it but didn't fully.

Other tables sync fine (`realtime_data`, `connection_log`, `statistics` all 200 OK). Bug is isolated to `drive_summary`.

## Root cause

Sprint 19 US-237 v0004 migration (`v0004_us237_drive_summary_reconcile.py`) chose to **ALTER** the legacy `drive_summary` table rather than DROP+CREATE it (the original Spool recommendation in TD-038 closure note). The ALTER added the 11 missing columns (source_id, source_device, drive_id, drive_start_timestamp, etc.) plus the `UNIQUE(source_device, source_id)` upsert key. **But it did not touch the legacy `device_id VARCHAR(64) NOT NULL` column.**

The Pi-side `SyncClient` upsert payload (in `src/pi/data/sync_client.py` or equivalent) doesn't populate `device_id` -- it uses `source_device` instead (which IS the modern attribution column). So every INSERT statement omits `device_id`, MariaDB tries to use the column's default (none), and rejects with `1364`.

## Why it shipped

- Sprint 19 US-237 acceptance criteria checked schema-additive correctness (new columns present + UNIQUE key created) but did not test "an actual Pi-shaped INSERT round-trips end-to-end on the modernized table"
- Sprint 19 deploy + Sprint 20 deploy both completed with `realtime_data` syncs proving sync IS reachable -- masked the table-specific failure
- Pre-Sprint-20 PM verification on 2026-04-29 saw `drive_summary status=failed` but attributed it to a pre-deploy state, not a post-migration regression
- New `tests/server/test_drive_summary_sync_post_reconcile.py` exists but apparently mocks at a layer that doesn't exercise the actual MariaDB column-set semantics

## Risk if not addressed

**Already actively dropping data on every sync.** Sprint 20 added drive_summary defer-INSERT (US-246) so cold-start metadata IS now Pi-side correct -- but the row never reaches server. Compounds with US-247/US-248 (Pi self-update) since update events log a drive_summary row that fails to sync.

Likelihood: certain (already happening). Impact: medium (no engine tuning data lost; just drive_summary metadata + sync_log status stuck).

## Remediation Plan

**Quick hotfix (recommended -- can run as one-line ALTER under sudo):**

```sql
ALTER TABLE drive_summary MODIFY device_id VARCHAR(64) NULL DEFAULT NULL;
```

This makes `device_id` nullable + provides a NULL default. The Pi-omitted-column INSERT now succeeds. `device_id` was the legacy attribution column from Sprint 7-8; it's superseded by `source_device` for Pi-syncs but kept around for analytics-side legacy compatibility.

**Slightly cleaner hotfix:**

Add v0007 migration (v0006 already exists for something else? verify) that ALTERs `device_id` to be nullable AND backfills `device_id = source_device` for any existing rows. Then future analytics queries can read either column.

**Longest-term fix:**

DROP the legacy `device_id` column entirely. Requires audit of every analytics query that joins or reads it; defer until Sprint 21+ when there's bandwidth for the audit.

## Sprint placement

**Sprint 21 P0 hotfix.** Should land as one of the first stories Sprint 21. Also: file follow-up on Sprint 19 US-237 acceptance gap -- the test that would have caught this is "INSERT against the actual modernized schema using a real Pi-shaped payload"; that's the kind of integration test feedback_runtime_validation_required.md targets.

## Related

- **TD-038** (drive_summary schema drift) -- closed by US-237 but apparently incomplete
- **US-237** (drive_summary 3-way reconciliation, Sprint 19) -- the migration that introduced the gap
- **TD-039** (schema-migration discipline) -- closed by US-249 (schema_diff CLI); the diff CLI may be able to flag this kind of NOT-NULL-without-default mismatch on next run
- **US-246** (drive_summary defer-INSERT, Sprint 20) -- compounds since it now writes Pi-side rows that never reach server

## Live workaround (interim)

Pi continues operating fine (other tables syncing). drive_summary rows stay Pi-only until TD-043 lands. CIO can run the one-line ALTER live to unblock immediately if desired.
