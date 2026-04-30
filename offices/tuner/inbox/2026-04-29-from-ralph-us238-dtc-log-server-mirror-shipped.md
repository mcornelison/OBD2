# US-238 SHIPPED — V-2 dtc_log server-side migration (0005) closed

**From:** Rex (Ralph, Agent 1)
**To:** Spool (Tuner SME)
**Date:** 2026-04-29
**Sprint:** 19 (Runtime Fixes + Server Reconciliation)
**Story:** US-238 — V-2 dtc_log server-side migration (0005)
**Status:** `passes:true` (Sprint 19 5/8)

---

## Why this matters for tuning

Sprint 15 US-204 added DSM-aware DTC retrieval (Mode 03 stored + Mode
07 pending with the 2G-firmware-aware probe). Drive 4 had `DTC_COUNT=0`
so the bug stayed dormant, but the next DTC drive would have produced a
`dtc_log` row on Pi only — the row never reached MariaDB because the
server table didn't exist (US-204 predated the US-213 migration registry,
so the ORM + sync wiring shipped without a deploy-time CREATE TABLE).

**With v0005 deployed:** every DTC the Eclipse throws now syncs to
chi-srv-01 within the standard ~30-min sync interval. The Pi → server
data path for DTCs is now in the same shape as `realtime_data`,
`drive_summary`, and `battery_health_log`.

The full Q1 of every engine review — *"is the check engine light on?"*
— now has a recorded answer that survives Pi restarts and cross-references
to your historical analysis on chi-srv-01.

---

## Schema (mirrors Pi `dtc_log_schema.py` US-204)

12 columns total: `id` PK + 4 sync (`source_id`, `source_device`,
`synced_at`, `sync_batch_id`) + 7 Pi-native:

| Column | Type | Notes |
|--------|------|-------|
| `dtc_code` | VARCHAR(16) NOT NULL | Five-character DTC e.g. `P0420`, `P0171`. Pi-side enforces format; server stores as-is. |
| `description` | TEXT NULL | Empty string for unknown / Mitsubishi P1XXX (never fabricated, US-204 invariant). |
| `status` | VARCHAR(16) NOT NULL | `stored` (Mode 03) or `pending` (Mode 07). `cleared` reserved for future MIL-clear capture. |
| `first_seen_timestamp` | DATETIME DEFAULT CURRENT_TIMESTAMP | US-202 canonical. Pi uses `strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`. |
| `last_seen_timestamp` | DATETIME DEFAULT CURRENT_TIMESTAMP | Bumped on duplicate within the same drive. |
| `drive_id` | INT NULL (indexed `ix_dtc_log_drive_id`) | US-200 inheritance from `getCurrentDriveId()`. NULL only if Mode 03 probe ran before drive_id minted (rare edge). |
| `data_source` | VARCHAR(16) DEFAULT 'real' | US-195 (`real` / `replay` / `physics_sim` / `fixture`). |

UNIQUE KEY `uq_dtc_log_source (source_device, source_id)` is the Pi-sync
upsert key — server side picks up `source_id` from Pi's `id` rename.

---

## Pi → server flow (post-deploy)

```
2G ECU --[K-line]--> OBDLink LX --[BT]--> Pi
  Pi DriveDetector._startDrive
    -> EventRouterMixin._handleDriveStart
      -> DtcLogger.logSessionStartDtcs
        -> Mode 03 GET_DTC          (stored)
        -> Mode 07 GET_CURRENT_DTC  (pending; probe-first per 2G firmware)
        -> rows INSERTed into Pi SQLite dtc_log

  Pi DELTA_SYNC_TABLES['dtc_log'] picked up by next ObdSyncClient run
    -> POST /api/v1/sync with dtc_log payload
    -> server runSyncUpsert
      -> _TABLE_REGISTRY['dtc_log'] -> DtcLog ORM upsert keyed
         on (source_device, source_id)
      -> rows land in MariaDB obd2db.dtc_log
```

Every DTC visible in your `/analyze` flow on chi-srv-01.

---

## What you can do with it

After Marcus's next deploy + the next CIO drive:

```sql
-- All DTCs from the Eclipse, most recent first
SELECT drive_id, dtc_code, status, description, first_seen_timestamp
FROM dtc_log
WHERE source_device = 'chi-eclipse-01'
ORDER BY first_seen_timestamp DESC;

-- Per-drive DTC count
SELECT drive_id, COUNT(*) AS dtc_count
FROM dtc_log
WHERE source_device = 'chi-eclipse-01'
GROUP BY drive_id
ORDER BY drive_id DESC;

-- Cross-reference DTC → drive_summary metadata
SELECT d.drive_id, d.starting_battery_v, d.ambient_temp_at_start_c,
       l.dtc_code, l.status
FROM drive_summary d
JOIN dtc_log l ON l.drive_id = d.drive_id
                AND l.source_device = d.source_device
WHERE d.source_device = 'chi-eclipse-01'
ORDER BY d.drive_id DESC, l.dtc_code;
```

The cross-reference query becomes meaningful once US-237's
drive_summary reconcile + US-236's defer-INSERT are also deployed —
that's all in Sprint 19's bundled deploy.

---

## DSM-specific gotchas (preserved from US-204 per knowledge.md)

1. **Mode 07 pending DTCs may return null on 2G firmware.** `DtcClient`
   probes once per connection and caches the verdict. If your post-deploy
   query shows zero `pending` rows for the Eclipse, the ECU has decided
   it doesn't support Mode 07 — that's a known 2G compliance gap, not
   missing data.
2. **Mitsubishi P1XXX descriptions land empty.** python-obd's DTC_MAP
   has only generic OBD-II codes. P1500 → `description=''`. The DSM
   cheat sheet you'd populate eventually (B-038?) would backfill these
   without rewriting the capture path.
3. **Same code in same drive = UPDATE, not INSERT.** `(drive_id, dtc_code)`
   uniquely identifies a row on the Pi; same code re-fires bumps
   `last_seen_timestamp`. Same code in a NEW drive INSERTs a fresh row
   — gives you per-drive recurrence visibility.

---

## What this story does NOT change

- Pi-side capture logic (US-204 stays intact)
- Mode 03 / Mode 07 retrieval semantics
- MIL rising-edge detection
- DTC Lifecycle invariants (1-6 in `specs/architecture.md` §10.5)
- Drive-end DTC re-fetch triggers
- Drive 5 baseline (this is server-side schema; no engine-data semantics
  shift)

---

## Sprint 19 status

5/8 done. Remaining 3 are all P1. Sprint will close once the operator
deploys (`bash deploy/deploy-server.sh` runs v0005 via the US-213
registry).

— Rex (Ralph, Session 110)
