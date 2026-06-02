# Server Schema Migration History — reference

> Extracted from `specs/architecture.md` §5 on 2026-06-01 to keep the main spec
> focused on the current schema. Contains the per-version migration registry
> (v0001–v0012) and the V0.28.0→V0.28.2 schema-normalization narratives **+ the
> Atlas Rule-10 design-gate records** (verbatim). The migration-system contract
> (how migrations are authored/run) stays in architecture.md §5; this is the
> per-version *history*. Authoritative ordered source remains
> `src/server/migrations/__init__.py::ALL_MIGRATIONS`.

**Registry (as of Sprint 19 close).**

| Version | Story | Purpose |
|---------|-------|---------|
| `0001` | US-209 | Retroactive catch-up: `data_source` (US-195) + `drive_id` / `drive_counter` (US-200) for capture/drive-id tables.  v0001 deliberately excluded `drive_summary` from CAPTURE_TABLES / DRIVE_ID_TABLES because Sprint 14 grooming treated it as analytics-only. |
| `0002` | US-217 | `CREATE TABLE battery_health_log` (Spool Session 6 Story 3 -- per-drain UPS health). |
| `0003` | US-223 | `DROP TABLE IF EXISTS battery_log` (TD-031 close -- dead Pi-only `BatteryMonitor` artifact). |
| `0004` | US-237 | `drive_summary` 3-way reconcile: ALTER 11 missing US-206/US-195/US-200 columns + add `IX_drive_summary_drive_id` + `uq_drive_summary_source` UNIQUE; cascade-delete the 9 Sprint-7-8 sim rows + their `drive_statistics` children (V-4 namespace cleanup, CIO 2026-04-29).  Closes Ralph's V-1 / V-4 from the post-Drive-4 health check. |
| `0005` | US-238 | `CREATE TABLE dtc_log` -- mirrors the `DtcLog` ORM declared in Sprint 15 US-204 but never CREATEd on live MariaDB (US-204 predates the US-213 explicit registry).  Twelve columns (id + 4 sync + 7 Pi-native) + `uq_dtc_log_source` UNIQUE + `ix_dtc_log_drive_id`.  Closes Ralph's V-2 (silent-data-loss-on-next-DTC-drive risk) from the post-Drive-4 health check. |

(Registry table above is Sprint-19-era; v0006-v0010 ship in the
`ALL_MIGRATIONS` list — `src/server/migrations/__init__.py` is the
authoritative ordered source. The V0.28.0 pass below documents v0010.)

### V0.28.0 Schema Pass — first slice (Sprint 43, F-076/F-107/F-108/F-109)

The V0.28.0 schema-normalization pass lands its schema surfaces through a
**single shared migration**,
`src/server/migrations/versions/v0010_us363_attribution_anomaly_data_quality.py`,
registered in `ALL_MIGRATIONS` (the explicit `MigrationRunner` registry,
TD-029 Path B — **not Alembic**; the "Alembic v0010" label in the PRD/sprint
docs is a naming nuance only). It is structured as ordered `_applyUsNNN`
substep functions sharing one `apply(ctx)`; each probes `INFORMATION_SCHEMA`
before issuing DDL (idempotent across fresh-`create_all`, prior-success, and
partial-recovery DBs) and re-probes after, raising `SchemaProbeError` on the
silent-no-op class. Substep order honors FK-cross-story dependencies (Atlas
Refinements row 16): rename → vehicle_info → dtc_freeze_frame → drive_summary
invariant. (A sixth surface, `speed_pid_calibration` / US-370, was built but
**deferred to V0.28.1** — see the §20 note; its substep insertion point stays
a reserved comment in v0010, so nothing it would have created ships in
Sprint 43.)

**1. `drive_summary.data_quality` — attribution-anomaly tripwire (US-363,
F-107).** `drive_summary` had **no** `data_quality` column; v0010 **ADDs**
`data_quality VARCHAR(16) NOT NULL DEFAULT 'full'` [**widened to VARCHAR(20) in
v0012 / US-377, V0.28.2** — the CHECK value `'attribution_anomaly'` is 19 chars;
see the V0.28.2 note below] + CHECK
`ck_drive_summary_data_quality (data_quality IN ('full','attribution_anomaly'))`
+ index. The enum is only `{full, attribution_anomaly}` — a summary has no
sample-count notion, so `sparse`/`below_threshold` (which `drive_statistics`
carries) are excluded. `drive_statistics`'s existing v0009 CHECK enum
(`full`/`sparse`/`below_threshold`) is **widened** to add
`attribution_anomaly` via DROP + re-ADD (MariaDB cannot widen a CHECK in
place). SSOT constants `DRIVE_SUMMARY_DATA_QUALITY_VALUES` /
`DRIVE_STATISTICS_DATA_QUALITY_VALUES` in `models.py`. This is the schema
behind Mechanism C in §10.7.1.

**2. `drive_statistics.drive_id` → `summary_id` rename (US-371, F-076).** The
column always held a `drive_summary.id` FK (server-minted PK), never a
Pi-assigned `drive_id`, so the old name lied to readers. v0010 issues
`ALTER TABLE drive_statistics RENAME COLUMN drive_id TO summary_id` (MariaDB
10.5.2+; the CHANGE-COLUMN fallback of conditionalOutcome 2 is not emitted).
**Complete rename, no alias.** Server-only (the Pi-side `drive_statistics`
table was retired entirely in US-351, §10.7). The composite PK +
`drive_summary.id` FK carry over automatically; `test_db_models.py` asserts
`summary_id` present AND `drive_id` absent.

**3. `vehicle_info` ECU-lineage columns + single-active marker (US-365,
F-108).** Five SERVER-ONLY columns added (the Pi never sends them;
`sync.py::_PRESERVE_ON_UPDATE` keeps them intact across re-syncs):
`ecu_signature TEXT NOT NULL`, `cal_signature TEXT NULL`,
`ecu_install_timestamp_utc DATETIME NOT NULL`,
`ecu_removal_timestamp_utc DATETIME NULL`, `notes TEXT NULL` (`DATETIME` not
`TIMESTAMP` to match the schema's other `*_utc` columns and dodge the epoch
range). A **STORED generated marker**
`ecu_active_marker INT AS (CASE WHEN ecu_removal_timestamp_utc IS NULL THEN 1
ELSE NULL END) STORED` + UNIQUE index `uq_vehicle_info_single_active`
enforces **exactly one active (un-removed) ECU** while permitting many closed
rows (NULL marker is not unique-constrained). **Append-only identity
invariant** (Spool Q4): identity columns are corrected by CLOSING the prior
row (`ecu_removal_timestamp_utc`) and OPENING a new one — never by in-place
UPDATE — because `dtc_freeze_frame` and per-drive joins reference a specific
row by FK + time window, so a mutated identity would silently rewrite
history. Surfaced as a SQL table comment (`VEHICLE_INFO_APPEND_ONLY_COMMENT`,
visible in `SHOW CREATE TABLE`); the `notes` column is the sanctioned
**mutable annotation lane** (Spool Q4 caveat). Sanctioned mutator
`stamp_ecu_swap`; reader `show_ecu_lineage` (US-366). Legacy backfill (US-365
/ AC#3): pre-tracking rows get the honest `PRE_TRACKING_UNKNOWN` sentinel +
a zero-length window (`install == removal == created_at`), so they are never
"currently active"; US-367's authoritative backfill overwrites these
placeholders with the real signatures (`MD346675` prior / `MD326328` new,
Spool-signed 2026-05-29).

**4. `dtc_freeze_frame` capture table (US-368, F-109).** New synced-capture
table (Mode 02 freeze-frame), CREATEd via the v0005 `CREATE TABLE IF NOT
EXISTS` + post-probe pattern, after the vehicle_info substep (FK target).
Columns: `id` PK, the standard synced-capture set (`source_id`,
`source_device`, `synced_at`, `sync_batch_id`, `UNIQUE(source_device,
source_id)`), `dtc_log_id` FK→`dtc_log(id)`, `captured_at_timestamp_utc`,
`pid_responses_json JSON`, `vehicle_info_id` FK→`vehicle_info(id)`, `notes`.
**Cross-tier VIN→id resolution (US-369):** Pi keys `vehicle_info` by
`vin TEXT`; server keys by integer `id` with ECU lineage. The temporal
invariant `ecu_install ≤ captured_at ≤ ecu_removal` lives server-side only
and is enforced by `src/server/api/dtc_freeze_frame.py::insertDtcFreezeFrame`,
which resolves `vehicle_info_id` from `(vin, captured_at)` and rejects a
bogus id (`ValueError`) before any partial insert.

**5. `drive_summary.drive_id ↔ source_id` invariant (US-372, F-076).** v0010
backfills BOTH asymmetric directions (`drive_id ← source_id` per AC#1 step i
— the real V0.27.x smell where a Pi-sync row's mirror was never populated;
and `source_id ← drive_id` per conditionalOutcome 1) **before**
`ADD CONSTRAINT chk_drive_id_source_id`, so the CHECK cannot fail on
pre-migration rows. Clause: `(drive_id IS NULL AND source_id IS NULL) OR
(drive_id IS NOT NULL AND source_id IS NOT NULL AND drive_id = source_id)`.
**The `IS NOT NULL` guards are load-bearing**: under SQL three-valued logic a
bare `drive_id = source_id` evaluates to NULL (which passes a CHECK) when
exactly one side is NULL, so the asymmetric smell row would slip through
without them. The invariant is **server-side**, established at the
sync-ingest boundary (`runSyncUpsert` mirrors the Pi-origin id onto both
columns) — the Pi-side `drive_summary` table has a single `drive_id` PK and
**no `source_id` column**. Q1 ruling 2026-05-28: backfill + invariant now;
the SSOT-purist column drop is deferred to later V0.28+ normalization.

*Gate-ratification note: this subsection added per PM Rule 10 + Atlas's
Sprint-43 PM Rule 13 PASS; documents the FINAL landed state of the five
shipping surfaces. Atlas Rule 10 PASS recorded 2026-05-29 (the deferred
`speed_pid_calibration` surface re-enters the doc when US-370 re-lands in
V0.28.1).*

### V0.28.1 — B-076 first slice (normalized ECU identity) (Sprint 44, US-376 + US-374)

The V0.28.1 patch sprint promotes ECU identity from the transitional snapshot
columns added in V0.28.0 (§5, point 3) to a normalized SSOT dimension table,
through a **forward-only** migration
`src/server/migrations/versions/v0011_us376_ecu_identity.py` (registered in
`ALL_MIGRATIONS` after v0010; **v0010 is left byte-for-byte untouched**). It
runs two ordered substeps — `_applyEcuTable` (US-376) then
`_applySpeedPidCalibrationRekey` (US-374, which depends on the `ecu` table
existing first) — each `INFORMATION_SCHEMA`-probed and re-probed for
idempotency across fresh-`create_all`, prior-success, and partial-recovery DBs.

**1. New `ecu` dimension table (US-376).** A pure, immutable identity dimension
keyed on the **`(ecu_signature, cal_signature)` PAIR** — both
`VARCHAR(32) NOT NULL`, `UNIQUE(ecu_signature, cal_signature)`
(`uq_ecu_signature_cal_signature`). It carries **no** lineage/timestamp
columns: the install/removal window stays on `vehicle_info`. A reflash is its
**own identity row** (a new pair + `-R2`/`-R3` cal), never an edit of an
existing row (Spool Q5, 2026-06-01 — SPEED correction is per-tune-state).
v0011 seeds 3 grounded rows: `(MD346675, 6675)` (prior 1998 factory FWD-turbo
flash ECU, drives ≤24), `(MD326328, UNKCAL)` (1997 board + ECMLink V3 flash,
drives ≥25), and `(PRE_TRACKING_UNKNOWN, PRE_TRACKING_UNKNOWN)` (the
pre-tracking sentinel, whose cal equals its signature).

**2. Immutability carve-out (Atlas Rule 13 refinement / Spool Q5 edge).** ECU
identity columns are immutable EXCEPT a single sanctioned write-once
`UNKCAL → real-CALID` same-row resolution (resolving a placeholder cal to the
ECU's real CALID is NOT a reflash, so it stays the same row). This slice builds
**no** resolution path — the carve-out is documentation honesty, surfaced in
the `ecu` table SQL comment (visible in `SHOW CREATE TABLE`), so the doc never
asserts absolute immutability the schema doesn't promise.

**3. `vehicle_info.ecu_id` FK — identity becomes SSOT (US-376).**
`fk_vehicle_info_ecu → ecu.id`, **NOT NULL**. The V0.28.0 transitional
`ecu_signature` / `cal_signature` TEXT columns are **KEPT this slice as a
derived snapshot** held coherent with the joined `ecu` row
(deprecated-transitional; a later B-076 slice drops them). Coherence is
enforced **read-side** by
`src/server/db/vehicle_info_coherence.py::findEcuCoherenceViolations` (zero
drift = text columns equal the joined `ecu` row). v0011 ADDs `ecu_id` nullable,
backfills by matching `(ecu_signature, COALESCE(cal_signature, ecu_signature))`
to the `ecu` row (the COALESCE maps v0010's legacy NULL-cal sentinel onto the
`PRE_TRACKING_UNKNOWN` seed), DERIVEs the transitional `cal_signature`,
**FAILs LOUDLY** on any unmatched row (never a NULL `ecu_id`), then MODIFY
NOT NULL + ADD FK. The `ALTER TABLE vehicle_info COMMENT=...` also lands the
full append-only + `ecu_id` table comment (v0010 never set it), so a migrated
production table converges with `create_all`.

**4. Writer discipline (US-376).** `stamp_ecu_swap` (US-366) now sets `ecu_id`
authoritative and DERIVEs the text columns from the resolved `ecu` row
(`resolveOrCreateEcu` in `_ecu_lineage_support.py`) — identity is written
through the FK, the snapshot columns follow.

**5. `speed_pid_calibration` re-key to `ecu_id` FK (US-374, F-076).** On dev,
v0010 creates `speed_pid_calibration` in the transitional **option-(c)**
`ecu_signature` natural-key shape (US-370 landed). v0011 substep (c) re-keys it
**forward**: the ORM `SpeedPidCalibration` drops `ecu_signature` and adds
`ecu_id` **NOT NULL FK → ecu.id** (`fk_speed_pid_calibration_ecu`) +
`UNIQUE(ecu_id)` (`uq_speed_pid_calibration_ecu_id`) — **one calibration row
per ECU identity**, so a reflash (its own `ecu` row) gets its own calibration
row. The migration ADDs `ecu_id` nullable, backfills by JOINing each row's
`ecu_signature` to its `ecu` row, **re-points the 2 seed provenance strings**
(`MD346675 → empirical-Drive-18-gear-math-fit`,
`MD326328 → gear-math-sanity-check-Drive-26-CIO-corrected`; correction factors
1.0 / 0.5 unchanged), FAILs LOUDLY on any unmatched row, MODIFY NOT NULL, ADD
UNIQUE + FK, then **DROPs** the old `uq_speed_pid_calibration_ecu_signature`
index (before the column — MariaDB requires the unique index gone first) and
the `ecu_signature` column. **Idempotency inverts** for a forward re-key — it
gates on the **DROPPED** column's presence (terminal absence of `ecu_signature`
= already re-keyed or fresh `create_all`). The writer
`insert_speed_pid_calibration` now takes `ecu_id` (the empty-`ecu_signature`
guard is gone — FK + NOT NULL cover it; the non-empty `provenance` guard is
kept); `select_empirical_calibrations` (`provenance LIKE 'empirical-%'`)
includes the prior-ECU empirical seed and excludes the new-ECU rough seed over
the FK shape. (Supersedes the V0.28.0 subsection's deferral parenthetical: the
option-(c) table did land in v0010 and is the re-key's starting point.)

*Gate-ratification note: this NEW V0.28.1 subsection added per PM Rule 10
(Marcus / PM, 2026-06-01) per US-376 AC#6 + US-374's joint Rule-10 clause;
documents the FINAL landed state of both shipping surfaces (server suite
`pytest tests/server -m "not slow"` = 1058 passed / 12 skipped / 0 failed;
ruff clean on all touched files). **Atlas Rule 10 PASS recorded 2026-06-01**
— verified against the LANDED code (`models.py` Ecu / VehicleInfo.ecu_id /
SpeedPidCalibration; `v0011_us376_ecu_identity.py`;
`vehicle_info_coherence.py`; `_ecu_lineage_support.py`), not the PRD
narrative: the `(ecu_signature, cal_signature)` pair key (both
`VARCHAR(32) NOT NULL`), the immutability carve-out, both `ecu_id` NOT NULL FK
shapes, the forward-only fail-loud backfill, and the per-tune-state re-key all
match the Atlas Q1–Q5 rulings + Spool Q5. Independently re-ran the gate:
US-376/US-374 test files 87 passed; full `pytest tests/server -m "not slow"`
green (exit 0, zero failures) on the Atlas box. **IRL acceptance pending** the
first V0.28-chain hardware deploy (deployed architecture intent, not yet
production-validated state); per CIO 2026-06-01 the formal PASS gates
`/sprint-validated`, not the deploy itself. Closes Watch List A-12 (the US-370
option-(c) code is now re-keyed forward to the SSOT `ecu_id` FK).*

*Seed correction (A-13, 2026-06-01): the new-ECU P/N was mis-recorded as
`MD335287`; the real value is **`MD326328`** (mfr `E2T61683`), Spool-signed
2026-06-01. Same physical ECU, mis-ID — a same-row value correction (cal stays
`UNKCAL`, `correction_factor` 0.5 + all FKs preserved), not a new identity/reflash.
Prod `ecu` id=2 corrected by direct UPDATE; the code seed sites corrected
all-coherently in US-378 (V0.28.2). The seed literals above now read `MD326328`.*

### V0.28.2 — `data_quality` column-width hotfix (Sprint 45, US-377)

The V0.28.1 IRL drill (2026-06-01) exposed a **width-vs-CHECK** defect on the
attribution-anomaly tripwire: both `drive_summary.data_quality` and
`drive_statistics.data_quality` were `VARCHAR(16)`, but their CHECK constraints
permit `'attribution_anomaly'` (**19 chars**). `recompute_drive_analytics` on
the dual-attribution drives 23+24 hit MariaDB `DataError 1406 ("Data too
long")`; SQLite (no VARCHAR-length enforcement) silently accepted it, so every
unit test passed — the **same SQLite-vs-MariaDB false-pass class** as the v0009
column gap (I-041), now extended to column *width*. No data corruption (failed
UPDATEs rolled back transactionally).

**Fix (forward-only `v0012`):** MODIFY both columns to **`VARCHAR(20)`**,
re-stating the full definition (`NOT NULL DEFAULT 'full'` — a bare `MODIFY …
VARCHAR(20)` would silently drop both). Idempotent via a
`CHARACTER_MAXIMUM_LENGTH` probe (widen only when narrower; fresh `create_all`
from the VARCHAR(20) ORM + re-runs are no-ops) with a post-condition width
re-probe (the v0002/v0009/v0010 silent-no-op guard). The width is now SSOT in
`models.DATA_QUALITY_COLUMN_LENGTH = 20`, read by both ORM columns and the
migration DDL; a **width-invariant test** scans ORM metadata and asserts every
CHECK-enum column is at least as wide as its longest permitted literal, so this
class cannot regress on any enum column.

*Gate-ratification note: this V0.28.2 subsection added per PM Rule 10 (Marcus /
PM, 2026-06-01) — corrects the V0.28.0 point-1 width and documents the v0012
widen. Server suite `pytest tests/server -m "not slow"` = 1081 passed / 12
skipped / 0 failed; ruff clean. **Atlas Rule 10 PASS: PENDING** — rides
`/sprint-validated` per the CIO 2026-06-01 deploy directive (same precedent as
the V0.28.1 subsection).*

---
