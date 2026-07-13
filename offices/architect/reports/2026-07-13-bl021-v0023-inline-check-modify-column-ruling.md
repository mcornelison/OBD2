# BL-021 ruling — v0023 must MODIFY COLUMN (not DROP CONSTRAINT/DROP CHECK); the stale CHECKs are inline column checks. A-10 4th cycle → TD-055 must graduate.

**Atlas (Architect) · 2026-07-13 · on-demand (CIO-tasked)**
**Refs:** BL-021, US-458, `v0023_us458_drop_stale_data_source_check.py`, BL-019/020, US-459/462, A-10/TD-055, F-116
**Verdict:** The fix hypothesis (`DROP CHECK`) is **WRONG** — proven invalid syntax on the real server. The verified fix is **`MODIFY COLUMN`** (the stale CHECKs are **inline column-level** checks, undroppable by `DROP CONSTRAINT`). No BLOCK on the patch. **BL-021 is the definitive proof case for TD-055's real-MariaDB migration test — that must now graduate to a funded story, not stay deferred.**

---

## 1. What failed

V0.29.10 deploy applied the defensive v0022 (US-461) cleanly — `schema_migrations`=0022 — then failed at v0023 (US-458, drop stale `data_source` CHECK):

```
ALTER TABLE profiles DROP CONSTRAINT data_source
ERROR 1091 (42000): Can't DROP CONSTRAINT `data_source`; check that it exists
```

Production SAFE: obd-server on V0.29.8, clean stop, no partial v0023, DB at v0022, Pi held.

## 2. Root cause — VERIFIED on the live server (not hypothesized)

The stale `data_source` CHECKs are **inline column-level constraints** (defined in the column definition, `data_source VARCHAR(16) ... CHECK (data_source IN (...))`), so MariaDB names each after its column. Live evidence (`prod_db_query`, obd2db, 2026-07-13):

- **All FIVE tables** carry the stale CHECK, **all named `data_source`** (= column), identical clause `` `data_source` in ('real','replay','physics_sim','fixture') ``: `calibration_sessions`, `connection_log`, `profiles`, `realtime_data`, `statistics`. (Not profiles-only — the fix is uniform across five.)
- `profiles` has exactly one constraint named `data_source`, type CHECK — so 1091 is the CHECK-name-equals-column-name collision, not multi-constraint ambiguity.
- All five still present, `schema_migrations`=0022 → no partial apply.

`v0023::apply` DISCOVERS these correctly (schema-wide `CHECK_CLAUSE LIKE '%data_source%'`, line 169) — discovery is sound. The bug is solely `dropConstraintSql` (line 137): `ALTER TABLE t DROP CONSTRAINT data_source` cannot drop an **inline** check whose name collides with the column.

### Scratch-table probe (real MariaDB 11.8.6 — the pass that earns the ruling)

I would not rule a version-specific DDL fix from docs (the MariaDB doc pages did not cleanly surface the drop semantics, and one web summary wrongly implied `DROP CHECK`). I reproduced it non-destructively on the live server with a throwaway table (`_atlas_bl021_probe`, created + dropped; zero real-data impact; confirmed removed):

| Candidate DDL | Real MariaDB 11.8.6 result |
|---|---|
| `DROP CONSTRAINT data_source` | **ERROR 1091** — reproduces the prod failure exactly |
| `DROP CHECK data_source` | **ERROR 1064 — syntax error.** `DROP CHECK` is **not valid MariaDB syntax** (that's MySQL). The BL-021 hypothesis fails; ruling it would have caused a 5th cycle. |
| `MODIFY COLUMN data_source VARCHAR(16)` | **OK** — inline CHECK removed (CHECK count → 0). **This is the fix.** |

## 3. Ruling

### Q1 — The correct + defensive v0023 fix: MODIFY COLUMN, discovery-driven, per-table, definition-preserving.

Keep v0023's discovery + post-probe (both sound). Replace the drop step:

- **Inline column-level CHECK** (discovered `constraint_name == 'data_source'`, i.e. == the checked column): drop it by **`ALTER TABLE {table} MODIFY COLUMN data_source <full current definition, minus the CHECK>`**. Verified working on 11.8.6.
- **Table-level CHECK** (a `ck_*`-style name ≠ the column, if any ever exists): `DROP CONSTRAINT {name}` (works for those, as v0015/v0022 use). None exist today — all five are inline — but branch on inline-vs-table so the migration is correct for either shape (the same probe-then-branch discipline as the BL-020 ruling).

**Preserve the full column definition** — a bare `MODIFY COLUMN data_source VARCHAR(16)` silently resets charset/collation. Introspect each column and rebuild faithfully. Verified live, all five identical:

```
data_source VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'real'
```

So each of the five becomes:
```sql
ALTER TABLE {table} MODIFY COLUMN data_source
  VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'real';
```
Introspect per-table (don't hardcode) so a future column-shape change can't drift the rebuild; the values above are the expected state to assert against.

**Idempotency / replay:** unchanged and clean — discovery returns 0 on a re-run (no CHECK left → nothing to MODIFY), the post-probe finds 0 survivors → success. The corrected v0023 replays over the current partial state (all five present, DB at 0022); re-deploy resumes at v0023.

### Q2 — The guard question, answered honestly: a topology guard would NOT have caught this; TD-055's real-MariaDB test would. Graduate it now.

Extending US-462's applied-schema guard to CHECK topology is **marginal for this class**: a topology guard asserts the desired *end-state* (no `data_source` CHECK) — it detects that drift exists, but it does not catch a **malformed DROP statement**. BL-021 is not undetected drift; it is migration code that is green on `create_all`/SQLite yet wrong against real MariaDB, because `DROP CONSTRAINT`-on-an-inline-CHECK is a MariaDB-11.8-specific behavior SQLite cannot reproduce.

The only thing that catches this class is **executing the migration chain against a real MariaDB** — TD-055's testcontainer third leg, which I have tracked since V0.27.18 and named as the "4th-cycle bug class" risk. **This is that 4th occurrence** (BL-019 → BL-020 → US-459-trap → BL-021). Ruling:

- **TD-055 (real-MariaDB migration-chain test) must graduate to a funded story now** — no longer deferrable defense-in-depth. Seed a MariaDB (matching the prod major, 11.x) with the known drift shapes (inline `data_source` CHECK; missing `drive_statistics` FK), run `apply_server_migrations` 0001→latest, assert clean. This would have caught BL-020 **and** BL-021 in CI, before deploy. Argus/QA + Ralph own the mechanics; I own the design gate.
- The US-462 CHECK-topology extension is **optional / low-value here** — do it only if it falls out cheaply from the FK guard; it is not the fix for this class. Do not let it substitute for TD-055.

## 4. Disposition

- **V0.29.11 patch, Story 1 (REQUIRED unblock):** v0023 drop step → per-table `MODIFY COLUMN` (definition-preserving, introspected), branch inline-vs-table, keep discovery + post-probe. Verified fix; re-deploy resumes at v0023 → releases held Pi deploy.
- **Story 2 (durable fix — the real one):** TD-055 real-MariaDB migration-chain test. Graduate from deferred to funded; this is the class that produced BL-019/020/021.
- **No BLOCK.** Rule-13 retired → this ruling is the gate. There is **no V0.29.11 PRD yet** — this ruling unblocks Marcus to scope it (same sequence as BL-020→V0.29.10). I'll design-gate that PRD when he drafts it.

## 5. Evidence

Live (`offices/pm/scripts/prod_db_query.sh`, chi-srv-01 obd2db, 2026-07-13): 5-table `data_source` CHECK enumeration + names; `profiles` TABLE_CONSTRAINTS (single CHECK, no ambiguity); column defs + charset/collation; **scratch-table `_atlas_bl021_probe` DDL probe** proving DROP CONSTRAINT→1091, DROP CHECK→1064-invalid, MODIFY COLUMN→OK (table created + dropped, confirmed removed). Migration source read in full (`v0023_us458_drop_stale_data_source_check.py:120-198`). MariaDB docs + KB cross-checked (docs did not settle it — the live probe did).
