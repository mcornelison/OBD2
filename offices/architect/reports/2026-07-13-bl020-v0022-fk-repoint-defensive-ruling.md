# BL-020 ruling — v0022 FK re-point must be 3-state defensive (A-10 drift, 3rd occurrence)

**Atlas (Architect) · 2026-07-13 · on-demand (CIO-tasked)**
**Refs:** BL-020, US-451, `v0022_us451_drive_identity_collapse.py`, A-10/TD-055, BL-019, US-459, F-104
**Verdict:** Marcus's defensive/idempotent approach is **CORRECT** — sharpened to a **3-state** probe-then-branch, and **verified add-safe** against the live DB. No BLOCK on the patch. The durable fix (applied-schema guard) is TD-055's long-deferred third leg finally coming due — recommend it lands in or immediately after V0.29.10.

---

## 1. What failed

`deploy-server.sh` applied migrations 0018→0021 (canonical `drives` table created + 27 rows back-filled) then raised at
`v0022::_repointSummaryFk` (`src/server/migrations/versions/v0022_us451_drive_identity_collapse.py:343-348`):

```
SchemaProbeError: drive_statistics.summary_id references neither drive_summary nor drives;
the expected FK is missing. Investigate the MariaDB session context.
```

Production is **SAFE**: obd-server stayed on V0.29.8 (failed before the version switch), clean stop, no partial FK damage.

## 2. Root cause — A-10 (ORM-vs-applied) drift, verified live

`_repointSummaryFk` (lines 323-376) assumes every table in the collapse currently carries an FK on `summary_id` — either → `drive_summary` (drop+re-point) or → `drives` (already done). It has **no branch for "no FK at all,"** and treats that third state as a fatal `SchemaProbeError` (lines 343-348).

That third state is exactly `drive_statistics`'s reality on prod. Verified via `prod_db_query` against live `obd2db` (2026-07-13):

| Table | rows | `summary_id` FK on prod | orphans vs `drives.drive_id` | col type |
|---|---|---|---|---|
| `drives` | 27 | PK `drive_id` | — | `int(11)` NOT NULL |
| `drive_statistics` | **434** | **NONE** | **0** | `int(11)` NOT NULL |
| `drive_derived_signals` | 1 | **stale** `fk_drive_derived_signals_summary` → `drive_summary(id)` (v0017 ALTER) | **0** | `int(11)` NOT NULL |
| `drive_annotations` | exists | **no `summary_id` column** (refs by `drive_id`, no FK) | n/a | — |

- `schema_migrations` MAX = **0021** (v0022 not recorded → clean stop).
- Substeps 1 (CHECK widen) + 2 (flag legacy) **already auto-committed** on prod (DDL is non-transactional in MariaDB): `ck_drives_data_quality` already contains `'unmappable_legacy'`; 0 rows have NULL `source_drive_id` so the flag was a legitimate no-op.

**Why the migration's own tests pass but prod fails:** the test DB is built by `Base.metadata.create_all`, which materializes the ORM's auto-named FK on `drive_statistics.summary_id` — so the drop+re-point path exists and works in-test. Prod is built by incremental ALTER migrations, and that auto-FK was **never ALTERed in**. This is the identical mocked-green / IRL-miss signature I flagged on **US-459 / BL-019** last week: a test asserting against ORM-materialized schema, not *applied* schema. Third occurrence of A-10 this sprint (BL-019 data_source CHECK → US-459 must-assert-applied → now BL-020 FK).

## 3. Ruling

### Q1 — Is the defensive/idempotent approach right? YES — as a **3-state** branch, per table.

`_repointSummaryFk` must resolve **three** states, not two:

1. **FK → `drive_summary` (stale):** drop by discovered name, then ADD → `drives(drive_id)`. *(This is the migration's current path; it is correct for `drive_derived_signals`.)*
2. **FK → `drives` (already re-pointed):** no-op. *(Idempotent replay.)*
3. **No FK at all:** **ADD** the canonical FK → `drives(drive_id)`, skip the drop. *(The missing branch; `drive_statistics`'s prod reality.)*

Concretely: at line 343, when `staleName is None` AND no `drives`-referencing FK exists, do **not** raise — fall through to the ADD DDL (`ADD_DRIVE_STATISTICS_FK_DDL` / `ADD_DRIVE_DERIVED_SIGNALS_FK_DDL`, which already exist at lines 174-185 and correctly use the ORM-matching names `fk_drive_statistics_drives` / `fk_drive_derived_signals_drives`). Apply this to **every** table in the collapse — never assume the ORM's FK is applied.

### The load-bearing safety check (verified, not assumed): the ADD **will succeed**.

`ADD FOREIGN KEY` validates existing rows and fails on any orphan or type mismatch. I did not take the docstring's "US-448 already aligned the values" on faith — I verified against prod:

- **0 orphans** on both `drive_statistics` (434 rows) and `drive_derived_signals` (1 row) — every `summary_id` value already exists in `drives.drive_id` (the v0018 subsume did align them).
- **Type-compatible**: all three columns are `int(11) NOT NULL`.

So add-if-missing is a **safe reconciliation**, not a hopeful guess.

### Replay over the partial-apply state is clean.

Fixed v0022 re-run over current prod: substep 1 → no-op (CHECK already widened); substep 2 → no-op (0 rows to flag, post-probe 0 survivors); substep 3 → `drive_statistics` ADD (state 3), `drive_derived_signals` drop+re-point (state 1). Re-deploy resumes at v0022 as Marcus scoped. No manual DB surgery needed.

### Q2 — Is the missing production FK itself a problem to reconcile? Add-if-missing IS the reconciliation.

The missing FK on `drive_statistics` is a *symptom* of the create_all-vs-ALTER drift, not a data-integrity fault (values aligned, 0 orphans). Adding the canonical `fk_drive_statistics_drives` → `drives(drive_id)` converges the applied schema onto the ORM and completes the F-104 identity collapse. Nothing further owed for the FK itself. The **systemic** drift (prod-by-ALTER vs ORM-by-create_all with nothing asserting parity) is the A-10 issue → Q3.

**Leave untouched (concur with the migration's design, lines 80-90):** do NOT add a hard `drive_summary.id → drives.drive_id` FK — the sync contract inserts `drive_summary` first (US-214) and new harness drives mint a divergent autoincrement (US-460); a hard FK there would break sync inserts and mis-point new rows. The collapse for `drive_summary` is correctly realized by the v0018 subsume + child re-points. Sound; do not disturb.

**`drive_annotations`:** exists on prod but has **no `summary_id` column** — genuinely outside the summary_id family, so the migration's "no-op" *conclusion* is right even though its stated *reason* ("no such table exists") is factually wrong on prod. Fix the comment to reflect reality (table exists, references `drives` by `drive_id`, no `summary_id` FK to re-point) so the next author isn't misled. Whether `drive_annotations` should carry a hard FK to `drives` is a separate hardening question, out of scope for BL-020 (no regression — it never had one).

### Q3 — Applied-schema FK guard? YES — and it must assert the **applied** schema, or it's theater.

This is the durable fix for the class and it has now fired 3× this sprint. The guard is the FK analogue of the US-459 `data_source` guard done **right**. The trap to avoid (the one US-459-as-first-scoped fell into): a guard built against a `create_all` DB always matches the ORM and **never** catches applied drift — it must assert `information_schema.KEY_COLUMN_USAGE` / `CHECK_CONSTRAINTS` topology against **applied** schema:

- **Achievable now (recommend for the patch):** a **deploy-preflight topology assertion** in `apply_server_migrations` / `deploy-server.sh` — before applying, dump the live target's FK+CHECK topology and compare to an expected manifest, failing loud with a remediation hint. Pure `information_schema` query on the deploy path, no testcontainer. Catches the drift at the moment it matters. Reuse US-459's applied-assert pattern.
- **Canonical / fuller (TD-055 third leg):** a **real-MariaDB testcontainer** that runs the migration chain 0001→latest and asserts applied FK/CHECK topology == expected. Highest fidelity, catches in CI. This is exactly the third leg I've tracked in A-10/TD-055 since V0.27.18 ("if it slips out of V0.28 grooming, a 4th-cycle bug class becomes possible" — we are now past that). If it can't be built in the patch, **file it explicitly** so it doesn't drift a 4th time.

**Standing design-discipline addition (I'll route to specs):** any migration that ALTERs FK or CHECK topology MUST probe-then-branch on the **applied** constraint state — never assume the ORM's declared constraint is applied. Fixed-v0022 becomes the reference instance.

## 4. Disposition

- **V0.29.10 patch, Story 1 (REQUIRED — the unblock):** make `_repointSummaryFk` 3-state defensive (add-if-missing), applied per table; fix the `drive_annotations` comment. Verified add-safe (0 orphans, int==int). Re-deploy resumes at v0022.
- **Story 2 (durable fix — strongly recommend it rides the patch, given 3 occurrences):** applied-schema FK/CHECK guard — deploy-preflight topology assertion (achievable now) + file the testcontainer third leg (TD-055) if not built now. Must assert applied schema, not create_all.
- **No BLOCK** on the patch shipping; Story 1 is the unblock, Story 2 is the durable fix.
- Ralph's lane: implement. Marcus's lane: scope/freeze/deploy. Rule-13 re-gate retired (CIO 2026-07-03) — this ruling is the architectural gate.

## 5. Evidence

Live queries (chi-srv-01 `obd2db`, `offices/pm/scripts/prod_db_query.sh`, 2026-07-13): FK landscape on `summary_id` columns; column types; row counts + `schema_migrations` MAX; orphan LEFT-JOIN check both tables; `drives.data_quality` CHECK clause + distribution; `drive_annotations` columns + FKs. Migration source read in full (`v0022_us451_drive_identity_collapse.py:323-401`). BL-020 + Marcus's inbox note cross-read.
