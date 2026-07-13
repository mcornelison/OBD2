# BL-021: v0023 (US-458 drop stale data_source CHECK) FAILS on live DB — DROP CONSTRAINT can't drop an EXISTING check (MariaDB name-collision); 4th A-10 cycle

| Field | Value |
|---|---|
| Severity | High (blocks V0.29.10 server deploy — Pi deploy held behind it) |
| Status | Active |
| Blocking | V0.29.10 server deploy (surfaced immediately after BL-020 cleared) |
| Waiting On | Atlas ruling + Ralph patch (V0.29.11) |
| Created | 2026-07-13 |
| Class | migration-vs-applied-DB mismatch (A-10 / TD-055) — **4th occurrence** (Atlas's "4th cycle" warning), after BL-019/BL-020 |

## Good news first — BL-020 is RESOLVED
V0.29.10 deploy ran the defensive v0022 (US-461) against production and it **applied cleanly** — `schema_migrations` now shows **0022** as latest applied. The 3-state FK re-point worked exactly as Atlas ruled. US-462's applied-schema preflight also ran and deferred honestly ("no applied-migration drive-identity FK to assert yet — deferring to the migration set").

## The new failure (v0023)
Deploy Step 4.5 then failed at **v0023 (US-458, drop stale data_source CHECK)**:
```
MigrationError: drop stale data_source CHECK 'data_source' on 'profiles' failed:
  ALTER TABLE profiles DROP CONSTRAINT data_source
ERROR 1091 (42000): Can't DROP CONSTRAINT `data_source`; check that it exists
```

## Live-DB evidence (prod_db_query, obd2db) — this is NOT "constraint missing"
- **`schema_migrations` at 0022** (v0022 applied; v0023 pending, not recorded).
- **The CHECK constraint EXISTS**: `information_schema.CHECK_CONSTRAINTS` → name `data_source`, clause `` `data_source` in ('real','replay','physics_sim','fixture') `` (the **stale** set, no `'foreign'` — exactly the constraint US-458 is meant to drop, the BL-019 root).
- **`data_source` is ALSO a column** on `profiles` (`varchar(16)`) → **name collision** (CHECK named same as its column).
- **MariaDB 11.8.6**-MariaDB-0+deb13u1.

So `DROP CONSTRAINT data_source` fails with 1091 even though the constraint is present — a MariaDB CHECK-vs-column name-collision quirk, not a missing object. Unlike BL-020 (object genuinely absent → ADD-if-missing), here the object is present but the drop **statement** can't resolve it.

## Production status — SAFE
- obd-server **active on V0.29.8** (deploy aborted at migrations, before any version switch/restart — no outage).
- Clean ALTER failure → **no partial v0023 apply**. DB at v0022.
- Pi deploy **HELD** (server must land first).

## The fix (Atlas ruling + Ralph patch V0.29.11)
- **Atlas:** rule the correct + defensive v0023 drop. Hypothesis (NOT prescriptive — your call): MariaDB needs `ALTER TABLE profiles DROP CHECK data_source` (CHECK-specific syntax) rather than `DROP CONSTRAINT` when the CHECK shares the column name; and/or a defensive existence-branch (drop-if-present, no-op-if-absent) so it survives both drift directions. Apply to **every** data_source table v0023 targets (not just profiles).
- **Broaden the guard?** US-462's applied-schema preflight covers FK topology; this is a CHECK-constraint drop. Worth extending the guard to assert CHECK topology too (your GAP-1 two-layer pattern), so this class is caught pre-deploy.
- **Ralph:** patch V0.29.11 (fork dev → fix v0023 → re-deploy resumes at v0023; 0018-0022 already applied).

## State to resume from
Server DB at migration 0022; v0023 pending. dev = V0.29.10 (f0da371). Pi HELD. Same drill as BL-020: Atlas ruling is the gate (Rule-13 retired).
