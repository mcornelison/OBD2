# Three Spool-side specs for Sprint 28+ grooming
**Date**: 2026-05-09
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — these unblock the analytics + drive-tagging path Spool needs once Sprint 28 bug-fixes ship.

## TL;DR

Three specs in this note. Each is a separate Sprint 28+ story candidate. Cross-referenced because they share schema:

1. **`mod_state` enum** — tag every drive with the car's modification level at capture time.
2. **`drive_annotations` table** — schema-side home for the tuning context I'm capturing manually right now (`offices/tuner/drive-annotations.md` + `obd_db.drive_annotations`).
3. **`drive_summary` writer contract** — what Spool needs from drive_summary as a tuner consumer; the broken writer (PM note Item 2 yesterday) needs to satisfy this.

I've already built a working `drive_annotations` table on chi-srv-01 (Spool-owned sidecar, populated for drives 3–7) per CIO authorization. Treat that as a prototype; the schema below is the formal spec. When Ralph migrates this in, the existing rows are easily migrated forward.

---

## Spec 1 — `mod_state` enum

### Purpose

Every drive is captured with the car in a specific modification state. **The same engine in different mod states behaves differently enough that comparing across states without tagging is dangerous.** A WOT pull on a Drive 7 baseline + a WOT pull on `ecmlink_e85_blend` should never be averaged together.

### Required values + transitions

| Value | Definition (mods present, cumulative) | Tuning-relevant changes vs prior state |
|---|---|---|
| `premod` | Current state. Stock turbo (TD04-13G), stock internals, modified EPROM, current bolt-ons (CAI / BOV / FPR / AN-6 fuel lines / oil catch can / fresh mounts / Luke clutch / coilovers / tie rods). Stock O2 sensors (narrowband). 91 octane pump gas. | Project baseline. All drives 3–7 are this state. |
| `walbro_installed` | + Walbro GSS342G fuel pump | Negligible at stock turbo + 91 (pump capacity headroom only matters under flow demand we don't yet see). Capture for completeness. |
| `flex_sensor_idle` | + GM flex fuel sensor wired inline (not yet active) | Same tuning behavior as walbro_installed; sensor sits idle until ECMLink reads it. |
| `exhaust_installed` | + 3" high-flow catted downpipe + 2.5–3" cat-back | **Significant**: better exhaust flow, slightly higher boost on stock wastegate possible, faster spool. Stock EPROM may or may not adapt cleanly. |
| `ecmlink_pump_gas_base` | + ECMLink V3 installed, base pump-gas tune, stock injectors | **Major**: ECU swap. New tune evolves throughout this state as Mike learns ECMLink. Expect multiple drives in this bucket; consider sub-sequencing if needed. |
| `ecmlink_pump_gas_wideband` | + AEM 30-0300 wideband feeding ECMLink | Tune is now data-driven (real AFR vs target). Same hardware as prior, different tune quality. |
| `ecmlink_pump_gas_id550` | + ID550 (550cc) injectors, rescaled in ECMLink | Larger injectors require rescaling. Pump gas tune redone. |
| `ecmlink_e85_blend` | + E85 map enabled, flex sensor active | **Major**: different fuel map per ethanol content. Flex blending. |
| `big_turbo_16g` | + 16G turbo (future, placeholder) | Different boost behavior, different MAF saturation point. |
| `big_turbo_20g` | + 20G turbo (future, placeholder) | Same family as 16G, more aggressive. |

### Transition trigger

`mod_state` advances to the next bucket the moment a mod is **installed and the car is driven for the first time post-install**. Pre-install and post-install drives must NOT share a value.

### Schema recommendation

- Column on `drive_summary` (and `drive_annotations`) — `VARCHAR(32) NOT NULL DEFAULT 'premod'` until the migration date is set, then drop the default.
- A small reference table `mod_state_history` (mod_state VARCHAR, installed_at DATE, notes TEXT) to track when each state began. Drive captured before the corresponding `installed_at` rolls back to the prior state.
- The Pi reads the **current** mod_state from config at drive-start (or at sync-time on the server). One-line config change in `config.json` whenever a mod ships.

### Acceptance criteria for the story

- All 5 existing drives (3, 4, 5, 6, 7) backfill to `premod`.
- Adding a new `mod_state` value requires only a config update, not a code change.
- Spool's drive-grading queries can `WHERE mod_state = ?` to constrain comparison to a single bucket.

---

## Spec 2 — `drive_annotations` table

### Purpose

Tuning-relevant context that the OBD telemetry doesn't record: fuel grade, fuel level, ambient conditions, driving intent, seat-of-pants observations. Currently captured manually in `offices/tuner/drive-annotations.md` and replicated to `obd2db.drive_annotations` (Spool-owned sidecar created 2026-05-09).

### Schema

```sql
CREATE TABLE drive_annotations (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  drive_id              INT NOT NULL,
  source_device         VARCHAR(64) NOT NULL DEFAULT 'chi-eclipse-01',
  captured_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  captured_by           VARCHAR(32) NOT NULL DEFAULT 'spool',

  -- Fuel chronology
  fuel_grade            SMALLINT,                 -- octane (87/89/91/93); -1 = E85; -2 = blend
  fuel_level_at_start   VARCHAR(16),              -- enum: F, 3/4, 1/2, 1/4, E, <1/4
  last_fill_date        DATE,                     -- nullable; date of most recent fuel fill before this drive

  -- Environment
  ambient_temp_f        DECIMAL(5,1),             -- ground-truth ambient at start (sensor or weather API)
  weather               VARCHAR(64),              -- free-form: "cloudy / sunny / rain / overcast"
  engine_soak_state     VARCHAR(32),              -- enum: cold, warm-restart (<30 min), hot-restart (<5 min)

  -- Drive context
  route                 VARCHAR(255),             -- free-form: "city", "mixed city/highway", specific roads
  driving_intent        VARCHAR(64),              -- enum: commute, errand, spirited, datalog_pull, system_test
  anything_unusual      TEXT,                     -- seat-of-pants observations
  is_actual_drive       BOOLEAN DEFAULT TRUE,     -- false = parked/idle system test

  -- Tag (FK to Spec 1)
  mod_state             VARCHAR(32) NOT NULL DEFAULT 'premod',

  -- Spool overlay
  spool_notes           TEXT,                     -- Spool's interpretive notes per drive

  UNIQUE KEY unique_drive (source_device, drive_id),
  INDEX idx_drive_id (drive_id),
  INDEX idx_mod_state (mod_state)
);
```

### Field semantics (where ambiguity is possible)

- **`fuel_grade`**: encode E85 as `-1` and pump-gas blends as `-2` so sort/aggregate behavior stays sane on integer column. Could also use VARCHAR; SMALLINT chosen for index efficiency.
- **`fuel_level_at_start`**: enum-as-string for human readability. Ordering rule: `E < <1/4 < 1/4 < 1/2 < 3/4 < F` — encode in app code, not DB.
- **`engine_soak_state`**: should be derivable from coolant_temp_at_start + barometric pressure trend + last_drive_end_timestamp. Future-scope: auto-derive from drive_summary instead of capturing manually.
- **`is_actual_drive`**: drives 3, 4, 5 are FALSE (parked-idle system tests). Drive 6, 7 are TRUE.

### Population path

Two possibilities:

1. **Manual** (current state) — Spool interviews CIO, writes rows.
2. **Semi-automated** — drive_end populates the row with ambient_temp + weather from a weather API call (per separate PM note 2026-05-09, weather-api feature idea), CIO supplies fuel + intent fields via a simple form (web UI, slash command, or sidecar markdown that gets parsed at sync time).

Spec target: get the schema in first; populate via #1 in the short term; ship #2 as a follow-up.

### Acceptance criteria

- 5 existing rows on `obd2db.drive_annotations` migrate cleanly into the new schema (no field shape mismatches).
- New rows are written by the Pi (or server) at drive_end, even with NULLs in fuel/intent fields if no UI exists yet.
- Spool can run `SELECT * FROM drive_summary JOIN drive_annotations ON drive_id` and get the full per-drive context without any other lookups.

---

## Spec 3 — `drive_summary` writer contract (Spool POV)

### Purpose

Yesterday's PM note flagged the `drive_summary` writer as P1 (broken across drives 3–7, missing entirely for 6–7). This spec defines what *correct* looks like from a tuner consumer's perspective so Ralph's fix has a non-negotiable bar to hit.

### Required behavior at drive-end

When a drive ends, the analytics writer MUST populate (in this order, atomically if possible):

1. `device_id` — the Pi
2. `drive_id` — the Pi-local counter (already present in current rows)
3. `start_time` — timestamp of first `realtime_data` row for this drive
4. `end_time` — timestamp of last `realtime_data` row for this drive
5. `duration_seconds` — `(end_time - start_time)` in seconds
6. `row_count` — `COUNT(*)` from `realtime_data WHERE drive_id = N`
7. `is_real` — TRUE if `>95%` of rows in the drive carry `data_source='real'`, FALSE otherwise
8. `data_source` — dominant value across rows (mode, not avg)
9. `drive_start_timestamp` — Pi-captured cranking entry timestamp (Pi-sync writes this; analytics doesn't override)
10. `ambient_temp_at_start_c` — Pi-captured at cranking entry
11. `starting_battery_v` — Pi-captured at cranking entry
12. `barometric_kpa_at_start` — Pi-captured at cranking entry

### Required behavior on race / partial state

The Pi-sync path writes columns 1–2 + 9–12 first; analytics writes 3–8 second. Both paths must respect `_PRESERVE_ON_UPDATE` (per existing `sync.py` contract) so Pi-sync re-syncing later doesn't clobber analytics columns.

If analytics fires before Pi-sync (race), analytics inserts a fully-populated row with NULLs in 9–12; Pi-sync later UPSERTs into the same row by `(source_device, source_id)` and only overwrites NULLs in its own columns. Same UNIQUE-key reconciliation pattern that's already in place.

### Required behavior on insufficient data

If `row_count < 100`:
- Still write the row.
- Set `is_real` = NULL (not FALSE — distinguishes "skipped" from "tested and failed").
- Spool's grading queries treat `row_count < 100 OR is_real IS NULL` as "drive not gradable, skip."

If `start_time IS NULL` after analytics fires (no `realtime_data` rows exist for this drive):
- Drive_summary row is effectively a stub. Set all stats columns to NULL, `is_real = FALSE`, write a row anyway.
- Spool's grading queries treat this as "data capture failed for this drive, escalate."

### What this contract DOES NOT cover

- The downstream `drive_statistics` writer — that's a separate consumer of drive_summary. Spec it later.
- Anomaly detection in `anomaly_log` — depends on baselines table existing first (PM note Item 1 yesterday).
- AI prompting in `analysis_history` — depends on drive_summary being correct, then a separate spec for prompt construction.

### Acceptance criteria

- All 5 existing drives' rows (3, 4, 5, 6, 7) get repopulated correctly when the writer fix ships.
- Drive 6 and 7 have rows where currently they have none.
- A future drive captured post-fix has all 12 fields populated by the time the drive_end event finishes processing.
- Spool can run a single query `SELECT * FROM drive_summary WHERE drive_id = N` and have everything needed to grade the drive (joined with `drive_annotations` for context, and `realtime_data` filtered on drive_id for the actual sensor data).

---

## Cross-spec story sequencing recommendation

The three specs interlock. Suggested order if you slot them into Sprint 28 or 29:

1. **Spec 3 first (drive_summary writer contract)** — P1 from yesterday, blocks all downstream analytics. Ship Sprint 28.
2. **Spec 1 second (mod_state enum)** — schema-only change, low-risk, unblocks Spool's drive-comparison queries. Could be Sprint 28 if there's room, otherwise Sprint 29.
3. **Spec 2 third (drive_annotations table)** — depends on Spec 1's `mod_state` column for the FK. Sprint 29.

Weather-API feature (separate note) lands after Spec 2's table exists.

— Spool
