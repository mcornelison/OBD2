# Manual SQL backfill -- server obd2db.battery_health_log rows 11-15 -- Spool to Ralph
**Date**: 2026-05-13
**Format**: A2AL/0.4.0
**Authority**: Mike directive 2026-05-13 -- one-shot manual, NOT a sprint story.

Task: backfill server-side `obd2db.battery_health_log` rows 11-15 with Pi-side close-event values. Server `end_timestamp` + `runtime_seconds` + `end_soc` currently NULL; Pi-side same rows closed cleanly. Forward sync UPDATE (V0.27.4 US-315) works for new drains -- confirmed drains 16 + 17 + 19. Historical rows stranded because US-315 doesn't auto-replay missed updates. US-327 wired backfill into deploy-server.sh + US-331 made script work cross-platform; no auto-run observed for these rows yet -- manual nudge needed.

## Source values

Pull from Pi authoritative:

```
ssh chi-eclipse-01 'sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db \
  "SELECT drain_event_id, end_timestamp, runtime_seconds, end_soc \
   FROM battery_health_log WHERE drain_event_id BETWEEN 11 AND 15 ORDER BY drain_event_id;"'
```

Expected (per Spool snapshot 2026-05-12T01:38Z):

| drain_event_id | end_timestamp | runtime_seconds | end_soc |
|---|---|---|---|
| 11 | 2026-05-10T00:52:28Z | 376 | 3.44375 |
| 12 | 2026-05-10T01:12:43Z | 15 | 3.78625 |
| 13 | 2026-05-10T02:34:59Z | 617 | 3.44375 |
| 14 | 2026-05-10T03:47:44Z | 726 | 3.41 |
| 15 | 2026-05-10T14:13:49Z | 786 | 3.445 |

Re-pull at backfill time -- table is the source of truth, not this note.

## Target

Server `obd2db.battery_health_log` -- access via `"C:\Program Files\MariaDB 12.2\bin\mysql.exe" -h chi-srv-01 -uobd2 -p<PWD> obd2db` (PWD in repo `.env` `DATABASE_URL`).

Server-side `id` = Pi-side `drain_event_id` for this era (1:1 mapping; US-194 `_renamePkToId` rename). Use `source_id` as the join key for safety.

## Safety protocol (per `reference_chi_srv_01_obd2db_access.md`)

1. Backup pre-run:
```
ssh chi-srv-01 'sudo -S mysqldump --single-transaction --quick obd2db battery_health_log > ~/backup/battery_health_log_$(date -u +%Y%m%dT%H%M%SZ).sql'
```

2. Wrap in transaction with verify-before-commit:

```sql
START TRANSACTION;

UPDATE battery_health_log SET end_timestamp = '2026-05-10 00:52:28', runtime_seconds = 376, end_soc = 3.44375
  WHERE id = 11 AND source_id = 11 AND end_timestamp IS NULL;
UPDATE battery_health_log SET end_timestamp = '2026-05-10 01:12:43', runtime_seconds = 15, end_soc = 3.78625
  WHERE id = 12 AND source_id = 12 AND end_timestamp IS NULL;
UPDATE battery_health_log SET end_timestamp = '2026-05-10 02:34:59', runtime_seconds = 617, end_soc = 3.44375
  WHERE id = 13 AND source_id = 13 AND end_timestamp IS NULL;
UPDATE battery_health_log SET end_timestamp = '2026-05-10 03:47:44', runtime_seconds = 726, end_soc = 3.41
  WHERE id = 14 AND source_id = 14 AND end_timestamp IS NULL;
UPDATE battery_health_log SET end_timestamp = '2026-05-10 14:13:49', runtime_seconds = 786, end_soc = 3.445
  WHERE id = 15 AND source_id = 15 AND end_timestamp IS NULL;

SELECT id, source_id, end_timestamp, runtime_seconds, end_soc FROM battery_health_log WHERE id BETWEEN 11 AND 15 ORDER BY id;
-- verify all 5 rows populated; if anything looks wrong: ROLLBACK;
COMMIT;
```

3. Show Mike pre-COMMIT per CIO downstream-of-his-hands rule.

## Idempotency

`AND end_timestamp IS NULL` clause prevents re-application if run twice. Safe to retry.

## After landing

- Server rows 11-15 closed -- matches Pi-side authoritative.
- V0.27.4 US-315 historical-stranded-rows side closes for this era.
- V0.27.8 US-327 + US-331 backfill chain pathway proven works manually -- followup TD for "make it actually fire on next deploy-server.sh" still open.

ack?

-- Spool
