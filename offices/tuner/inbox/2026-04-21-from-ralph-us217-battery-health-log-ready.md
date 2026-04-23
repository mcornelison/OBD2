# US-217 Battery Health Log — Ready for Use

**From:** Rex (Ralph Agent 1)
**To:** Spool (Tuner SME)
**Date:** 2026-04-21
**Sprint:** 16 — Wiring
**Story:** US-217 Battery health tracking schema

## TL;DR

`battery_health_log` table + `BatteryHealthRecorder` writer + CLI helper landed on the Pi side. Server mirror + sync registration + deploy-time MariaDB migration all in place. CIO can record monthly drain tests today via:

```bash
python scripts/record_drain_test.py \
    --start-soc 100 --end-soc 20 --runtime 1440 \
    --load-class test --ambient 22 --notes "April baseline"
python scripts/sync_now.py
```

## What shipped

| Layer | File | Purpose |
|-------|------|---------|
| Pi schema + writer | `src/pi/power/battery_health.py` (new) | DDL, idempotent migration helper, `BatteryHealthRecorder` with `startDrainEvent` + `endDrainEvent` (close-once semantic) |
| Pi DB wiring | `src/pi/obdii/database.py` | `ObdDatabase.initialize()` calls `ensureBatteryHealthLogTable` |
| Pi sync registration | `src/pi/data/sync_log.py` | `PK_COLUMN['battery_health_log'] = 'drain_event_id'` |
| Server model | `src/server/db/models.py` | `BatteryHealthLog` SQLAlchemy class with `UNIQUE(source_device, source_id)` |
| Server sync | `src/server/api/sync.py` | Registered in `_TABLE_REGISTRY` |
| Server migration | `src/server/migrations/versions/v0002_us217_battery_health_log.py` (new) + `__init__.py` | Deploy-time MariaDB CREATE TABLE via US-213 registry |
| CLI | `scripts/record_drain_test.py` (new) | One-shot manual drain recorder |
| Specs | `specs/architecture.md` | New "Battery Health Log (US-217)" subsection in §5 |
| Docs | `docs/testing.md` | New "Monthly UPS Drain Test (CIO-facing, US-217)" 5-step protocol |
| Tests | 3 new files, 46 tests, 0 regressions | Schema, recorder, server sync |

## Schema shape (matches your Session 6 grounding refs)

```sql
CREATE TABLE battery_health_log (
    drain_event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    start_timestamp TEXT NOT NULL DEFAULT (canonical ISO-8601 UTC),
    end_timestamp   TEXT,
    start_soc       REAL NOT NULL,
    end_soc         REAL,
    runtime_seconds INTEGER,
    ambient_temp_c  REAL,
    load_class      TEXT NOT NULL DEFAULT 'production'
                    CHECK (load_class IN ('production','test','sim')),
    notes           TEXT,
    data_source     TEXT NOT NULL DEFAULT 'real'
                    CHECK (data_source IN ('real','replay','physics_sim','fixture'))
);
CREATE INDEX IX_battery_health_log_start ON battery_health_log(start_timestamp);
```

## load_class enum (per your Session 6 design + Marcus grooming)

- `production` — real drain (wall power lost while Pi was running normally). US-216's Power-Down Orchestrator will write these automatically when it ships.
- `test` — CIO's scheduled monthly drill (what `record_drain_test.py` writes by default? actually no — CLI default is `production`; CIO must pass `--load-class test` for drills).
- `sim` — developer / CI synthetic drain.

## Close-once semantic (worth knowing)

`endDrainEvent` is idempotent on re-call — first close wins, second call returns the stored values without overwriting. Rationale: if US-216's orchestrator crashes between WARNING-stage open and TRIGGER-stage close, a retry on next boot must not blow away the original close data.

## Hand-off to US-216

When you start US-216 (after your power audit lands), the recorder is ready to consume:

```python
from src.pi.power.battery_health import BatteryHealthRecorder
recorder = BatteryHealthRecorder(database=db)

# At WARNING stage (30% SOC):
event_id = recorder.startDrainEvent(startSoc=30.0, loadClass='production')

# At TRIGGER stage (20% SOC), just before systemctl poweroff:
recorder.endDrainEvent(drainEventId=event_id, endSoc=20.0)
```

US-216 owns the staged shutdown ladder + the wiring to UpsMonitor. US-217 only owns the schema + writer surface.

## Battery-replacement threshold (your Session 6 design)

Per your "Battery-replacement alert when runtime drops >30% from baseline" grounding ref — this is the analytics rule, NOT yet implemented. Recommend filing it as a future story (analytics consumer of this table) once we have a baseline + a few drills under our belt.

## What was NOT in scope (US-216 territory)

- Staged shutdown ladder (warning/imminent/trigger SOC stage transitions).
- Hysteresis / oscillation guard.
- `systemctl poweroff` integration.
- Auto-write of `production` rows from the orchestrator.
- `config.json` shutdown threshold section.

## Verification snapshot (Pi side)

```bash
ssh mcornelison@chi-eclipse-01 \
  "sqlite3 ~/Projects/Eclipse-01/data/obd.db '.schema battery_health_log'"
```

(Re-run `python src/pi/main.py --dry-run` once at next deploy to trigger the idempotent migration.)

## Deploy notes for Marcus

The MariaDB-side `battery_health_log` table will be created on the next `deploy/deploy-server.sh` run via the migration registry (US-213). The migration is idempotent — safe to re-deploy.

## Next available work

After this lands, US-218 (I-017 specs↔agent.md dedup) and US-219 (US-175 Spool review ritual wiring) remain as independent S-size stories. US-216 still gated on your power audit inbox note.

— Rex
