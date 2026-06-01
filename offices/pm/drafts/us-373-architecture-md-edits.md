# US-373 — `specs/architecture.md` edits (DRAFT for Atlas Rule 10 review)

- **Sprint:** 43 / V0.28.0 (`sprint/sprint43-V0.28.0`)
- **Story:** US-373 (F-105, type: housekeeping) — PM Rule 10 design-gate DoD
- **Author:** Marcus (PM), 2026-05-29 — transcribing the ratified 4-way V0.28 schema-pass design + landed code into doc form. **PM does not make architecture calls (Rule 3); this is a transcription for Atlas's Rule 10 PASS.**
- **Status:** DRAFT, ALL 6 SURFACES NOW LANDED (US-370 landed 2026-05-29) — NOT yet in `specs/architecture.md`. Awaiting Atlas **re-PASS on surface 5**, then PM lands all three edits verbatim + marks US-373 `passes: true`.

## Why this is (still) staged, not yet landed

US-373's conditionalOutcome #2 requires §5.X to document the **final landed state** of all 6 schema surfaces. As of 2026-05-29 all six are landed and verified (US-363/365/368/371/372 + US-370). Atlas already PASSed surfaces 1–4+6 + §10.7.1 on 2026-05-29; surface 5 (`speed_pid_calibration`, US-370) landed afterward and is now drafted to its **final landed shape** below — it needs Atlas's **re-PASS** before PM lands. Atlas asked to re-PASS *before* the edits hit `specs/architecture.md` (his PASS-note sequencing), so the doc stays clean until then.

## Doc-structure note (conditionalOutcome #3 — RULED by Atlas 2026-05-29)

- **EDIT 1** = appended `### 10.7.1` subsection after the "Idempotent recompute principle" block (§10.7 already uses numeric subsections §10.5/§10.6/§10.7; consistent; §10.6 F-7/F-8 precedent). ✓
- **EDIT 2** = a new **descriptive `###` heading** (NOT "§5.X" — §5 uses descriptive headings, not numeric §5.N), titled `### V0.28.0 Schema Pass — first slice (Sprint 43, F-076/F-107/F-108/F-109)`, placed **immediately after `### Server Schema Migrations (US-213, TD-029 closure)`** (~line 980, its natural migration-history sibling). One cohesive subsection — **do NOT split per-Feature** (the 6 surfaces share one migration v0010; splitting fragments that narrative).

## Rule 10 status — Atlas PASS recorded 2026-05-29

Atlas verified against landed code + v0010 + ORM (not this transcription) and granted **PASS on §10.7.1 + schema surfaces 1–4+6** (2026-05-29), clearing the conditional Rule 10 gate on US-361/363/365/371/372. **Surface 5 (`speed_pid_calibration`) is now landed (US-370, option-(c)) and drafted to final shape above — awaiting Atlas re-PASS.** Inbox: `offices/pm/inbox/2026-05-29-from-atlas-us373-rule10-PASS-plus-2-rulings.md`.

---

## EDIT 1 — append to §10.7 (after the existing "Idempotent recompute principle" block)

### 10.7.1 DriveDetector dual-attribution remediation (F-107, Sprint 43 / V0.28.0)

**Defect of record.** The V0.27.18 IRL drill (2026-05-22) produced two `drive_id`s (drives 23 + 24) for one physical leg: time-overlapping `realtime_data` rows, ~2× polling cadence, RPM readings 1500–2000 apart within the same second. RCA: `offices/ralph/findings/2026-05-28-drive-detector-dual-attribution-rca.md`. This is a Pi-side defect upstream of the §10.7 B-104 Step 1 architecture (it predates and is orthogonal to the Pi=emitter/server=authority shift) and was carved out of the V0.27 chain merge as a known scoped exception.

The remediation is **defense-in-depth across three tiers** — a Pi detector fix, an optional Pi process guard, and a server-side observability tripwire — because the evidence has two distinct root causes (a single process minting a spurious second drive, and two concurrent processes each minting their own).

**Mechanism A — ECU-silence continuation (Pi detector, LIVE; US-361).**
`src/pi/obdii/drive/detector.py`: an ECU-silence-inferred `drive_end` (quiet OBD link ⇒ inferred engine-off) is now **tentative**, not terminal. When `_checkEcuSilenceDriveEnd` fires it records the closed `drive_id` + time; if the engine demonstrably resumes (RPM back above the start threshold) within `MIN_INTER_DRIVE_SECONDS` (5 s — the previously-defined-but-unused constant the RCA named), the next `_startDrive` **re-attaches to the prior `drive_id`** instead of minting a second. RPM-debounce and forced (`forceKeyOff`) ends never arm the marker, so confirmed-engine-off drives still mint fresh — US-229 silence behavior and the US-311 warm-restart e2e are untouched.

**Mechanism B — single-instance guard (Pi orchestrator, ships DEFAULT-OFF; US-361).**
The production drives-23/24 evidence is two **concurrent** `eclipse-obd` orchestrator processes; a single process cannot produce overlap because `drive_id` is a process-global singleton, so a detector fix alone cannot prevent it. New `src/pi/obdii/orchestrator/single_instance.py` (`SingleInstanceGuard`, pidfile + injectable liveness seam) makes a second concurrent process refuse to start — wired as step-0 of `_initializeAllComponents`, released last in `_shutdownAllComponents`. **Ships behind `pi.runtime.singleInstanceGuard.enabled` (default `False`) — and stays dark for V0.28.0 (Atlas ruling 2026-05-29, CIO-ratified).** The guard's as-built failure mode is the silent-wrong-winner class the V0.27 chain spent itself killing: a live peer holding the pidfile makes the *newly-deployed* process silently refuse and exit while the *stale* one keeps running (it reclaims only dead pids), which under a US-354 deploy-hygiene miss actively enforces the V0.27.16 "running old code despite new `.deploy-version`" pathology. Mechanisms A + C already cover the observed defect (A prevents the single-process re-mint; C makes any overlap — including the two-process case — observable as `attribution_anomaly`), so for a defect seen exactly once, observability is the honest posture rather than a load-bearing boot-path refuse. **Production-enable is gated on BOTH: (1) the Mechanism C tripwire flagging a second, independent two-concurrent-process overlap in production (the case demonstrably recurs); AND (2) the refuse path made loud + deploy-visible (WARN/ERROR + nonzero exit the deploy script checks) plus a deploy-hygiene check proving `systemctl restart` release-then-acquire ordering** — incremental US-361 follow-up, not this sprint.

**Mechanism C — server-side `attribution_anomaly` tripwire (LIVE; US-362 + US-363).**
`src/server/analytics/overlap.py::detect_overlapping_drives` is the SSOT detector over raw `realtime_data` (US-362). US-363 wires it into both server compute paths so an overlapping drive is stamped `data_quality='attribution_anomaly'`, surfacing the dual-emission pattern downstream as a per-row flag — **observability, not refusal** (the analytics are still computed; the flag marks them for human disposition). The on-demand CLI `python -m src.server.cli.recompute_drive_analytics` surfaces an `[ATTRIBUTION_ANOMALY]` marker on affected drives. The schema surfaces this needed are in §5.X.

**IRL execution deferred (US-364).** The production-DB backfill — `recompute_drive_analytics --drive-id 23/24/25` against chi-srv-01, idempotent re-run zero-diff, and release of the `regression_manifest` F-005 + F-007 HOLDs on the observed result — runs as part of the Sprint-43 IRL validation drill, not a headless dev iteration (BL-022). It executes the already-built path; it does not change the architecture documented here.

*Gate-ratification note: §10.7.1 added per the 2026-05-18 design-gate governance rule (PM Rule 10) + Atlas's Sprint-43 PM Rule 13 validation-block PASS. Mechanism B's production-enable disposition is an Atlas Rule 10 call recorded here + in §20.*

---

## EDIT 2 — new §5 subsection (V0.28.0 schema pass)

### V0.28.0 Schema Pass — first slice (Sprint 43, F-076/F-107/F-108/F-109)

*(Placement: immediately after `### Server Schema Migrations (US-213, TD-029 closure)`, ~line 980 — Atlas doc-structure ruling 2026-05-29.)*

The V0.28.0 schema-normalization pass lands five schema surfaces through a **single shared migration**, `src/server/migrations/versions/v0010_us363_attribution_anomaly_data_quality.py`. **This repo uses the explicit `MigrationRunner` registry (TD-029 Path B), NOT Alembic** — the "Alembic v0010" label in the PRD/sprint docs is a naming nuance only; the file is registered in `ALL_MIGRATIONS` and structured as ordered `_applyUsNNN` substep functions sharing one `apply(ctx)`. Each substep probes `INFORMATION_SCHEMA` before issuing DDL (idempotent across fresh-`create_all`, prior-success, and partial-recovery DBs) and re-probes after, raising `SchemaProbeError` on the silent-no-op class. Substep order honors FK-cross-story dependencies (Atlas Refinements row 16): rename → vehicle_info → dtc_freeze_frame → (US-370 insertion point) → drive_summary invariant.

**1. `drive_summary.data_quality` — attribution-anomaly tripwire (US-363, F-107).**
`drive_summary` had **no** `data_quality` column; v0010 **ADDs** `data_quality VARCHAR(16) NOT NULL DEFAULT 'full'` + `CHECK ck_drive_summary_data_quality (data_quality IN ('full','attribution_anomaly'))` + index `idx_drive_summary_data_quality`. The enum is deliberately only `{full, attribution_anomaly}` — a summary has no sample-count notion, so `sparse`/`below_threshold` (which `drive_statistics` carries) are excluded. `drive_statistics`'s existing v0009 CHECK enum (`full`/`sparse`/`below_threshold`) is **widened** to add `attribution_anomaly` via DROP + re-ADD `ck_drive_statistics_data_quality` (MariaDB cannot widen a CHECK in place). SSOT constants: `DRIVE_SUMMARY_DATA_QUALITY_VALUES`, `DRIVE_STATISTICS_DATA_QUALITY_VALUES` in `models.py`.

**2. `drive_statistics.drive_id` → `summary_id` rename (US-371, F-076).**
The column always held a `drive_summary.id` FK (server-minted PK), never a Pi-assigned `drive_id`, so the old name lied to readers. v0010 issues `ALTER TABLE drive_statistics RENAME COLUMN drive_id TO summary_id` (MariaDB 10.5.2+; chi-srv-01 is well above — the CHANGE-COLUMN fallback of conditionalOutcome 2 is not emitted). **Complete rename, no alias.** Server-only (Pi-side `drive_statistics` was retired entirely in US-351, §10.7). The composite PK + `drive_summary.id` FK carry over to the new name automatically. ORM `DriveStatistic.summary_id`; `test_db_models.py` asserts `summary_id` present AND `drive_id` absent.

**3. `vehicle_info` ECU-lineage columns + single-active marker (US-365, F-108).**
Five SERVER-ONLY columns added to `vehicle_info` (the Pi never sends them; `sync.py::_PRESERVE_ON_UPDATE` keeps them intact across re-syncs):
- `ecu_signature TEXT NOT NULL`, `cal_signature TEXT NULL`, `ecu_install_timestamp_utc DATETIME NOT NULL`, `ecu_removal_timestamp_utc DATETIME NULL`, `notes TEXT NULL`.
- `DATETIME` (not `TIMESTAMP`) matches the schema's other `*_utc` columns and dodges the TIMESTAMP epoch range; the AC's "TIMESTAMP" is the generic term.
- A **STORED generated marker** `ecu_active_marker INT AS (CASE WHEN ecu_removal_timestamp_utc IS NULL THEN 1 ELSE NULL END) STORED` + UNIQUE index `uq_vehicle_info_single_active` enforces **exactly one active (un-removed) ECU** while permitting many closed rows (NULL marker is not unique-constrained). Marker expr is the SSOT `VEHICLE_INFO_ACTIVE_MARKER_EXPR`, shared between ORM and migration DDL.
- **Append-only identity invariant** (Spool Q4): the identity columns are corrected by CLOSING the prior row (`ecu_removal_timestamp_utc`) and OPENING a new one — never by in-place UPDATE — because `dtc_freeze_frame` and per-drive joins reference a specific row by FK + time window, so a mutated identity would silently rewrite history. Surfaced as a SQL table comment (`VEHICLE_INFO_APPEND_ONLY_COMMENT`, visible in `SHOW CREATE TABLE`). The `notes TEXT` column is the sanctioned **mutable annotation lane** (Spool Q4 caveat — forensic notes about a running ECU without forcing a close+open). Sanctioned mutator: `stamp_ecu_swap` (US-366); reader: `show_ecu_lineage` (US-366).
- **Legacy backfill (US-365 / AC#3):** pre-tracking rows get the honest `PRE_TRACKING_UNKNOWN` sentinel signature (never a fabricated ECU id) and a zero-length window (`install == removal == created_at`), so they are never "currently active" and never collide on the marker. US-367's authoritative backfill (Spool-signed real signatures + install/removal timestamps) overwrites these placeholders.

**4. `dtc_freeze_frame` capture table (US-368, F-109).**
New synced-capture table (Mode 02 freeze-frame), CREATEd via the v0005 `CREATE TABLE IF NOT EXISTS` + post-probe pattern, after the vehicle_info substep (FK target). Columns: `id` PK, the standard synced-capture set (`source_id`, `source_device`, `synced_at`, `sync_batch_id`, `UNIQUE(source_device, source_id)`), `dtc_log_id` FK→`dtc_log(id)`, `captured_at_timestamp_utc`, `pid_responses_json JSON`, `vehicle_info_id` FK→`vehicle_info(id)`, `notes`. **Cross-tier VIN→id resolution (US-369 implements):** Pi keys `vehicle_info` by `vin TEXT`; server keys by integer `id` with ECU lineage. The temporal invariant `ecu_install ≤ captured_at ≤ ecu_removal` lives server-side only (Pi schema has no ECU-lineage columns) and is enforced by `src/server/api/dtc_freeze_frame.py::insertDtcFreezeFrame`, which resolves the server `vehicle_info_id` from `(vin, captured_at)` and rejects a bogus id (`ValueError`) before any partial insert.

**5. `speed_pid_calibration` — per-ECU SPEED-PID correction (US-370, F-076) — ✅ LANDED 2026-05-29.**
New per-ECU SPEED-PID correction-factor table (the new ECU reads ~2× actual ground speed). Built to Atlas option-(c); ORM `SpeedPidCalibration` + SSOT constants in `models.py` (table count 21→22); writer + analytics gate in `src/server/analytics/speed_pid_calibration.py`; server-only (no Pi files); server suite 1004 passed.
- **`ecu_signature` is this table's OWN natural key — `VARCHAR(32) NOT NULL`, UNIQUE, NO FK to `vehicle_info`** (Atlas ruling option (c)). The correction factor is a property of the ECU signature *itself*, stable across install windows, so this table is the SSOT for "per-ECU SPEED correction," keyed by signature. The two tables share the signature *value* (a natural key) — **not** the payload-denormalization Spool VETOed. A UNIQUE on `vehicle_info.ecu_signature` was rejected (breaks the append-only lineage invariant US-365 landed — same signature legitimately recurs across install windows); a FK to `vehicle_info.id` was rejected (binds a window-invariant factor to one window). `VARCHAR(32)` (Spool sign-off) gives a clean unique key with no MySQL prefix-length hack + headroom over the 8-char `MDxxxxxx` form (truncating a unique natural key = silent collision). **`vehicle_info.ecu_signature` remains `TEXT` (its landed US-365 shape); the TEXT↔VARCHAR(32) value-match join is functional — type-consistency normalization is a separate routed decision, not part of this surface.**
- Columns: `id` PK; `ecu_signature VARCHAR(32) NOT NULL UNIQUE`; `correction_factor DOUBLE NOT NULL`; `capture_method VARCHAR(32)` + CHECK enum `{gps_correlation, gear_math, vendor_spec, default}` (F-076 §1 ENUM realized as VARCHAR+CHECK for SQLite parity, NULL-allowed); `captured_at_timestamp_utc`, `captured_by`, `provenance TEXT NOT NULL`, `notes` (nullable).
- **2 seed rows** (`INSERT IGNORE`, idempotent on the UNIQUE key): `MD346675` → `1.0`, `provenance='gear-math-drive-18-3rd-gear-fit'` (prior ECU, SPEED reads correct); `MD335287` → `0.5`, `provenance='rough-seed-drive-26-gear-math'`, `notes` carries `INITIAL ESTIMATE` + Q2 cross-ref (new ECU ~2× drift; rough Drive-26 gear-math estimate; refine post-GPS-correlation drive). Both seeds `capture_method='gear_math'` — the honest method tag for a gear-math-derived value; pending-GPS status lives in `notes` (PM-accepted deviation from CO#2's `'default'`, which was conditional on a pure GPS-defer Spool did not choose).
- **`provenance TEXT NOT NULL`** (Spool Q2 caveat) makes rough-seed vs empirical vs gps-correlated auditable at query time; the writer (`insert_speed_pid_calibration`) rejects empty/whitespace `provenance` or `ecu_signature` (ValueError), and `select_empirical_calibrations()` returns only `provenance LIKE 'empirical-%'` so rough/gear-math seeds are excluded from empirical analytics.
- Migration substep `_applySpeedPidCalibrationTable` landed at the reserved `# ---- US-370 substep appends here ----` in v0010 `apply()`, after the `vehicle_info` substep (ordering documented per Atlas Refinements row 16), CREATE TABLE IF NOT EXISTS + `serverTableExists` short-circuit + post-probe (US-368 pattern).
- **Deferred upgrade path (B-076, not this sprint):** the textbook normalization is a dedicated `ecu` identity table (surrogate PK + UNIQUE signature) that both `vehicle_info` and `speed_pid_calibration` FK; introducing it now over-scopes a 2-row seed. On Atlas's Watch List for the next groom.

**6. `drive_summary.drive_id ↔ source_id` invariant (US-372, F-076).**
v0010 backfills BOTH asymmetric directions (`drive_id ← source_id` per AC#1 step i — the real V0.27.x smell where a Pi-sync row's mirror was never populated; and `source_id ← drive_id` per conditionalOutcome 1) **before** `ADD CONSTRAINT chk_drive_id_source_id`, so the CHECK cannot fail on pre-migration rows. Clause: `(drive_id IS NULL AND source_id IS NULL) OR (drive_id IS NOT NULL AND source_id IS NOT NULL AND drive_id = source_id)`. **The `IS NOT NULL` guards are load-bearing**: under SQL three-valued logic a bare `drive_id = source_id` evaluates to NULL (which passes a CHECK) when exactly one side is NULL, so the asymmetric smell row would slip through without them. The invariant is **server-side**, established at the sync-ingest boundary (`runSyncUpsert` mirrors the Pi-origin id onto both columns) — the Pi-side `drive_summary` table has a single `drive_id` PK and **no `source_id` column** (so AC#2/V-5's "Pi-side set both" is N/A for the Pi; corrects an earlier Rex note). Q1 ruling 2026-05-28: backfill + invariant now; the SSOT-purist column drop is deferred to later V0.28+ normalization.

*Gate-ratification note: §5.X added per PM Rule 10 + Atlas's Sprint-43 PM Rule 13 PASS. Documents FINAL landed state of all 6 surfaces (surface 5 landed 2026-05-29 via US-370).*

---

## EDIT 3 — header + §20 changelog

- **Header "Last Updated":** bump to V0.28.0 ship date with the Atlas-gated tag (matching the §10.6/§10.7 precedent), once the sprint ships. Draft tag: `Last Updated: <V0.28.0 ship date> (US-373, PM; Atlas-gated per Rule 10)`.
- **§20 new row (top of table):**

| Date | Author | Description |
|------|--------|-------------|
| <V0.28.0 ship date> | Marcus (US-373, PM; Atlas Rule 10 PASS) | §10.7.1 "DriveDetector dual-attribution remediation (F-107)" appended: Mechanism A ECU-silence continuation (US-361, Pi detector, LIVE), Mechanism B single-instance guard (US-361, default-OFF; production-enable gated per Atlas 2026-05-29 keep-dark ruling), Mechanism C server-side `attribution_anomaly` tripwire (US-362 detector + US-363 wiring); US-364 IRL backfill deferred to drill. New §5.X "V0.28.0 Schema Pass — first slice" documents the single shared `MigrationRunner` v0010 (NOT Alembic) + 5 surfaces: `drive_summary.data_quality` ADD + `drive_statistics` CHECK widen (US-363); `drive_statistics.drive_id`→`summary_id` complete rename (US-371); `vehicle_info` ECU-lineage 5 cols + STORED single-active marker + append-only invariant + notes annotation lane (US-365); `dtc_freeze_frame` capture table + cross-tier VIN→id temporal invariant (US-368/369); `speed_pid_calibration` per-ECU correction (US-370, PENDING); `drive_summary.drive_id↔source_id` CHECK invariant (US-372). Atlas Rule 10 PASS recorded BEFORE `/sprint-deploy-pm`. |

## Open items — Atlas rulings 2026-05-29 (all RESOLVED)

1. ~~Mechanism B production-enable disposition~~ → **RULED: keep dark** (CIO-ratified). Folded into §10.7.1 above.
2. ~~US-370 `speed_pid_calibration` FK-target shape~~ → **RULED: option (c)** — `ecu_signature VARCHAR UNIQUE` natural key, no FK. Folded into surface 5 above.
3. ~~§5 subsection numbering / per-Feature split~~ → **RULED: descriptive `###` heading after Server Schema Migrations; no split.** Folded into doc-structure note above.

## Remaining path to US-373 `passes: true`

1. **Spool** signs off the ECU-signature naming convention + `VARCHAR` length + seed values (requested 2026-05-29) → unblocks US-367 + US-370 build.
2. **US-370 builds** in the option-(c) shape (Ralph iteration or folded into IRL close).
3. **Atlas re-PASSes surface 5** once US-370 lands.
4. **PM lands all three edits** into `specs/architecture.md` verbatim, bumps the header "Last Updated", records the PASS in the §20 row → marks US-373 `passes: true`.
5. No `/sprint-deploy-pm` until then (Rule 13 gate). US-364 + US-367 IRL execution rides the CIO Sprint-43 drill.
